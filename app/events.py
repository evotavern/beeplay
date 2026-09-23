"""Everything that leaves a trace: log lines, audit rows, team alerts.

Every line is one JSON object on stdout (so it lands in the journal) and in
config.EVENTS_LOG, so a game's whole history is one grep away:

    grep '"work_id": 12' /var/lib/beeplay/logs/events.jsonl
"""

import json
import sys
import threading
import urllib.request

from sqlalchemy.orm import Session

from app import config
from app.models import User, Work, WorkEvent, utcnow

_write_lock = threading.Lock()


def log_event(event: str, **fields) -> None:
    line = json.dumps(
        {"event": event, "at": utcnow().isoformat(timespec="seconds") + "Z", **fields},
        ensure_ascii=False,
        default=str,
    )
    print(line, file=sys.stdout, flush=True)
    with _write_lock:
        config.EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with config.EVENTS_LOG.open("a", encoding="utf-8") as log:
            log.write(line + "\n")


def record(
    session: Session,
    work: Work,
    *,
    actor: str,
    kind: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Add an audit row for a change to `work`; the caller commits."""
    session.add(
        WorkEvent(
            work_id=work.id,
            actor=actor,
            kind=kind,
            before=json.dumps(before, ensure_ascii=False) if before is not None else None,
            after=json.dumps(after, ensure_ascii=False) if after is not None else None,
        )
    )
    owner = session.get(User, work.user_id) if work.user_id else None
    log_event(
        kind,
        work_id=work.id,
        title=work.title,
        slug=owner.slug if owner else None,
        artifact=work.artifact_hash,
        actor=actor,
        before=before,
        after=after,
    )


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except Exception as error:  # an alert must never break the request that raised it
        log_event("alert_failed", error=repr(error))


def alert(text: str, *, wait: bool = False) -> None:
    """Tell the team. A no-op until BEEPLAY_ALERT_WEBHOOK is set."""
    if not config.ALERT_WEBHOOK:
        return
    payload = {"msg_type": "text", "content": {"text": text}}
    if wait:
        _post(config.ALERT_WEBHOOK, payload)
    else:
        threading.Thread(target=_post, args=(config.ALERT_WEBHOOK, payload), daemon=True).start()
