"""Durable jobs, bounded one-shot requests and credential-free instrumentation.

Run with a single uvicorn process. Worker threads claim jobs transactionally;
startup fails interrupted requests instead of silently paying to replay them.
"""
import hashlib
import html as html_module
import http.client
import json
import re
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from sqlalchemy import select, text

from app import config, db, events
from app.game_imports import inject_reporter
from app.models import Generation, GenerationAttempt, GenerationEvent, GenerationKey, utcnow

# Job lifecycle. The error codes a failed job carries are mirrored as
# user-facing messages in assets/js/generation.js.
QUEUED, GENERATING, VALIDATING = "queued", "generating", "validating"
READY, PUBLISHED, FAILED = "ready", "published", "failed"
ACTIVE = (QUEUED, GENERATING, VALIDATING)
PLAYABLE = (READY, PUBLISHED)

# Serialises this process's read-then-write sequences on generation rows
# (idempotent submit, publish-once, key rotation). SQLite's own writer lock
# covers the job claim, which must also hold across processes.
LOCK = threading.RLock()
MAX_RESPONSE = 512 * 1024
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'")
SYSTEM_PROMPT = """Create one complete, small, delightful mobile browser game from the user's idea.
Return ONLY a complete HTML document, starting with <!doctype html>, with a head and body.
Use inline CSS and classic (non-module) vanilla JavaScript, canvas or DOM. No markdown, explanation, dependencies,
external assets, network calls, imports, storage, iframes, forms, or navigation.
Use procedural shapes/emoji, responsive layout, touch/pointer controls and keyboard where useful.
Include brief instructions, an immediately playable core loop, score/win/lose feedback and restart.
Fit a phone viewport, prevent accidental scrolling while playing, make controls large.
Implement one mechanic well. Keep the code readable and within the output budget; simplify
visuals rather than compressing expressions or leaving unfinished code.
Honor an explicit user request for 2D or 3D; otherwise use the assigned rendering mode.
For 2D use canvas/DOM. For 3D use simple world-space x/y/z geometry with camera projection,
depth sorting and perspective on Canvas 2D; no external engine or CDN is available.
Initialize state before drawing, use explicit DOM lookups (never implicit element-id globals),
check canvas contexts and provide fallbacks for optional APIs such as roundRect.
Draw a visible first frame immediately. Keep resize separate from restarting game state.
Before returning, review every script for valid syntax, balanced delimiters, valid numeric
literals (e.g. 0.22), defined variables and a working start, input, score and restart path.
The surrounding app handles title, cover and publishing. Do not ask questions.
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects carrying a provider credential to another host."""

    def redirect_request(self, *args, **kwargs):
        return None


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def emit(session, job, kind, elapsed_ms=None):
    session.add(GenerationEvent(generation_id=job.id, kind=kind, elapsed_ms=elapsed_ms))
    events.log_event("generation_" + kind, generation_id=job.id, model=job.model, elapsed_ms=elapsed_ms)


def elapsed(job):
    return max(0, int((utcnow() - job.created_at).total_seconds() * 1000))


def since_ms(start, end):
    return max(0, int((end - start).total_seconds() * 1000))


def update_timings(job, **values):
    """Merge values into the job's timings JSON and return the result."""
    timings = json.loads(job.timings)
    timings.update(values)
    job.timings = json.dumps(timings)
    return timings


def choose_key(excluded):
    with LOCK, db.SessionLocal() as session:
        now = utcnow()
        choices = []
        for raw in config.EVOMAP_KEYS:
            key_id = fingerprint(raw)
            row = session.get(GenerationKey, key_id)
            if row is None:
                row = GenerationKey(id=key_id, disabled=False)
                session.add(row)
            if key_id not in excluded and not row.disabled and (row.cooldown_until is None or row.cooldown_until <= now):
                choices.append((row, raw))
        if not choices:
            session.commit()
            return None
        # Least recently used first; never-used keys sort before all others.
        row, raw = min(choices, key=lambda pair: pair[0].last_used_at or datetime.min)
        row.last_used_at = now
        session.commit()
        return row.id, raw


def cooldown(headers):
    value = headers.get("retry-after", "60")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            seconds = 60
    return min(86400, max(1, seconds))


def request_game(key, model, prompt, rendering_mode="2D"):
    request = urllib.request.Request(
        config.EVOMAP_BASE_URL + "/chat/completions",
        data=json.dumps({"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\nAssigned rendering mode: " + rendering_mode}, {"role": "user", "content": prompt}],
            "max_tokens": config.GENERATION_MAX_TOKENS, "stream": False}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=config.GENERATION_TIMEOUT_S) as response:
            status, headers, raw = response.status, response.headers, response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        status, headers, raw = error.code, error.headers, error.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("response_too_large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        data = {}
    return status, {k.lower(): v for k, v in headers.items()}, data


def safe_usage(data):
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        return {}
    return {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage.get(k), int) and not isinstance(usage[k], bool) and usage[k] >= 0}


def safe_limits(headers):
    # Never retain arbitrary headers or error bodies: they may echo a key.
    names = ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
             "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
             "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens")
    return {k: str(headers[k])[:128] for k in names if k in headers}


class GameScripts(HTMLParser):
    """Extract executable code for parsing only; generated code is never run here."""
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name, value in attrs.items():
            if name.startswith("on") and value:
                self.scripts.append("function handler(event){\n" + value + "\n}")
        if tag == "script":
            kind = (attrs.get("type") or "").strip().lower()
            if "src" in attrs or kind == "module":
                raise ValueError("unsupported_script")
            if kind not in ("application/json", "application/ld+json"):
                # Include legacy executable MIME types as well as ordinary scripts.
                self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def validate_scripts(content):
    parser = GameScripts()
    parser.feed(content)
    if parser.current is not None:
        raise ValueError("incomplete_script")
    # One isolated parser process; vm.Script compiles but does not execute code.
    checker = "const vm=require('node:vm');const fs=require('node:fs');for(const s of JSON.parse(fs.readFileSync(0,'utf8')))new vm.Script(s);"
    try:
        result = subprocess.run(["node", "--max-old-space-size=64", "-e", checker],
                                input=json.dumps(parser.scripts), text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("script_validator_unavailable") from error
    if result.returncode:
        raise ValueError("invalid_javascript")


def normalize_html(content):
    if not isinstance(content, str):
        raise ValueError("missing_html")
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:html)?\s*", "", content, flags=re.I)
        content = re.sub(r"\s*```$", "", content).strip()
    if len(content.encode()) > 256 * 1024 or not re.search(r"<html[\s>]", content, re.I) or not re.search(r"</html>\s*$", content, re.I):
        raise ValueError("incomplete_html")
    match = re.search(r"<head(?:\s[^>]*)?>", content, re.I)
    if not match:
        raise ValueError("missing_head")
    validate_scripts(content)
    # Policy comes before all model-authored markup. The HTTP sandbox also
    # applies when this document is opened directly, outside the app iframe.
    policy = '<meta http-equiv="Content-Security-Policy" content="' + html_module.escape(CSP, quote=True) + '">'
    # Prefix policy so even malformed model markup before <head> is covered.
    return policy + inject_reporter(content.encode()).decode()


def fail(job_id, code):
    with db.SessionLocal() as session:
        job = session.get(Generation, job_id)
        job.status, job.error, job.finished_at = FAILED, code, utcnow()
        emit(session, job, "failed", elapsed(job))
        session.commit()


# Why the provider refused a request. Classified here rather than stored raw:
# error bodies may echo a key. Only these reasons take a key out of rotation.
DISABLING = ("invalid_key", "quota_exhausted")
# Reasons worth trying the job's next key for.
RETRYABLE = DISABLING + ("rate_limited", "model_not_allowed", "forbidden")


def rejection_reason(status, data):
    if status is None or status == 200:
        return None
    error = data.get("error", {}) if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {}
    code, message = error.get("code"), str(error.get("message") or "").lower()
    if status == 401:
        return "invalid_key"
    if status == 402 or (status == 429 and code in ("insufficient_quota", "quota_exceeded")):
        return "quota_exhausted"
    if status == 429:
        return "rate_limited"
    if status == 403:
        # A valid key without access to this model: a deployment setting to fix
        # (BEEPLAY_EVOMAP_MODEL), not a reason to stop using the key.
        return "model_not_allowed" if "not allowed to use model" in message else "forbidden"
    return "server_error" if status >= 500 else "rejected"


def pool_exhausted_error(reasons):
    """The job error once no key is left, naming the most actionable cause."""
    if "model_not_allowed" in reasons:
        return "model_unavailable"
    if "forbidden" in reasons:
        return "provider_forbidden"
    return "keys_unavailable"


def run_job(job_id):
    with db.SessionLocal() as session:
        job = session.get(Generation, job_id)
        model, prompt = job.model, job.prompt
        # UUID-derived assignment is stable across key retries and uniformly distributed.
        rendering_mode = "3D" if int(hashlib.sha256(job.id.encode()).hexdigest()[-1], 16) % 2 else "2D"
        update_timings(job, rendering_mode=rendering_mode, prompt_version=2)
        session.commit()
    excluded = set()
    reasons = set()
    while True:
        selected = choose_key(excluded)
        if selected is None:
            fail(job_id, pool_exhausted_error(reasons))
            return
        key_id, raw_key = selected
        excluded.add(key_id)
        start = time.monotonic()
        status, headers, data = None, {}, {}
        error = None
        try:
            status, headers, data = request_game(raw_key, model, prompt, rendering_mode)
        except (OSError, http.client.HTTPException, ValueError):
            # Network failure, timeout or oversized body: the completion state
            # is unknown, so no automatic retry/duplicate spending. Anything
            # else is a bug and reaches Worker.loop, which logs it.
            error = "provider_connection_failed"
        latency = int((time.monotonic() - start) * 1000)
        reason = rejection_reason(status, data)
        with LOCK, db.SessionLocal() as session:
            row = session.get(GenerationKey, key_id)
            if reason in DISABLING:
                row.disabled = True
            elif reason == "rate_limited":
                row.cooldown_until = utcnow() + timedelta(seconds=cooldown(headers))
            attempt = GenerationAttempt(generation_id=job_id, key_id=key_id, model=model,
                status=error or ("ok" if status == 200 else "provider_rejected"),
                http_status=status, reason=reason, latency_ms=latency,
                usage=json.dumps(safe_usage(data)), limits=json.dumps(safe_limits(headers)))
            session.add(attempt)
            session.commit()
        events.log_event("generation_provider_attempt", generation_id=job_id, key_id=key_id,
                         model=model, http_status=status, reason=reason, latency_ms=latency,
                         usage=safe_usage(data), limits=safe_limits(headers), error=error)
        if reason in RETRYABLE:
            reasons.add(reason)
            continue
        if error or status != 200:
            fail(job_id, error or "provider_error")
            return
        break
    with LOCK, db.SessionLocal() as session:
        job = session.get(Generation, job_id)
        job.status = VALIDATING
        update_timings(job, provider_ms=sum(session.scalars(
            select(GenerationAttempt.latency_ms).where(GenerationAttempt.generation_id == job_id))))
        session.commit()
    start = time.monotonic()
    try:
        choice = data["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("incomplete_output")
        document = normalize_html(choice["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        fail(job_id, "invalid_game")
        return
    with LOCK, db.SessionLocal() as session:
        job = session.get(Generation, job_id)
        job.html, job.status, job.finished_at = document, READY, utcnow()
        timings = update_timings(job, validation_ms=int((time.monotonic() - start) * 1000),
                                 playable_ms=elapsed(job), output_bytes=len(document.encode()))
        if job.details_at:
            timings = update_timings(job, idle_wait_ms=since_ms(job.details_at, job.finished_at))
        emit(session, job, READY, timings["playable_ms"])
        session.commit()


class Worker:
    def __init__(self):
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        with db.SessionLocal() as session:
            for job in session.scalars(select(Generation).where(Generation.status.in_((GENERATING, VALIDATING)))):
                job.status, job.error, job.finished_at = FAILED, "interrupted", utcnow()
                emit(session, job, "interrupted", elapsed(job))
            session.commit()
        if config.EVOMAP_KEYS:
            for _ in range(config.GENERATION_WORKERS):
                thread = threading.Thread(target=self.loop, daemon=True)
                thread.start()
                self.threads.append(thread)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=1)

    def claim(self):
        """Move the oldest queued job to generating and return its id."""
        with db.SessionLocal() as session:
            # Take SQLite's writer lock before reading, so two workers can
            # never claim the same job.
            session.execute(text("BEGIN IMMEDIATE"))
            job = session.scalar(select(Generation).where(Generation.status == QUEUED).order_by(Generation.created_at))
            if job is None:
                session.commit()
                return None
            job.status = GENERATING
            update_timings(job, queue_ms=elapsed(job), max_tokens=config.GENERATION_MAX_TOKENS, prompt_version=2)
            emit(session, job, "started", elapsed(job))
            session.commit()
            return job.id

    def loop(self):
        while not self.stop.is_set():
            job_id = None
            try:
                job_id = self.claim()
                if job_id:
                    run_job(job_id)
            except Exception as error:
                # The traceback goes to the journal; the event log keeps only
                # the exception type, since a message could echo a key.
                traceback.print_exc()
                events.log_event("generation_worker_error", generation_id=job_id, error=type(error).__name__)
                if job_id:
                    try:
                        fail(job_id, "internal_error")
                    except Exception:
                        traceback.print_exc()
            self.stop.wait(0.25)
