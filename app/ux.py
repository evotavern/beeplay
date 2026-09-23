"""What players ran into since the last check, for `beeplay-ops ux`.

Reads the failure events in events.jsonl (http_error, client_error from the
page reporter, and health_fail from the game reporter) and groups them by area
and then by person (app/people.py), so one player stuck in a loop reads as one
finding rather than a pile of requests. Each person gets an outcome from the
success events (creation_ok, play_ok) and, where the page reported it, the
message the failure put in front of them. 404/405s from requests without a
BeePlay cookie are scanners: counted, never listed.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import browsers

AREAS = ("creation", "gameplay", "other")
DEFAULT_WINDOW = timedelta(hours=24)
NOISE_STATUSES = {404, 405}

STUCK = "stuck"
OPEN = "no success since"
RECOVERED = "recovered"
UNKNOWN = "outcome unknown"
_OUTCOME_ORDER = {STUCK: 0, OPEN: 1, RECOVERED: 2, UNKNOWN: 3}
_LEGACY = "ua-"

_ID_SEGMENT = re.compile(r"/\d+(?=/|$)")
_PUBLISH = re.compile(r"/api/generations/[^/]+/publish")
_NEXT = {"stayed": "stayed on the page", "redirected": "sent to another page", "closed": "dialog closed"}


def is_creation_path(path: str) -> bool:
    return path.startswith(("/api/import-game", "/api/generations")) or path == "/create"


def is_creation_success(method: str, path: str) -> bool:
    return method == "POST" and (path == "/api/import-game" or bool(_PUBLISH.fullmatch(path)))


@dataclass
class Source:
    """One entry in the report: a person (or, for old events, a browser string)."""

    key: str
    area: str
    failures: Counter = field(default_factory=Counter)
    browsers: Counter = field(default_factory=Counter)
    who: set = field(default_factory=set)
    saw: Counter = field(default_factory=Counter)
    inferred: dict = field(default_factory=dict)
    first_at: str | None = None
    last_at: str | None = None
    last_success_at: str | None = None

    @property
    def total(self) -> int:
        return sum(self.failures.values())

    @property
    def legacy(self) -> bool:
        """Logged before person ids and success events: grouped by browser only."""
        return self.key.startswith(_LEGACY)

    @property
    def outcome(self) -> str:
        if self.legacy:
            return UNKNOWN
        if self.last_success_at and self.last_at and self.last_success_at > self.last_at:
            return RECOVERED
        return STUCK if self.total >= 2 else OPEN

    @property
    def in_app_only(self) -> bool:
        return bool(self.browsers) and set(self.browsers) <= browsers.IN_APP


@dataclass
class Summary:
    areas: dict[str, list[Source]]
    noise: int = 0


def parse_duration(text: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([mhd])", text.strip())
    if not match:
        raise ValueError(f"not a duration: {text!r} (try 30m, 2h, 1d)")
    amount, unit = int(match[1]), match[2]
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]


def _at(event: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(event["at"].rstrip("Z"))
    except (KeyError, TypeError, ValueError):
        return None


def read_events(log: Path, *, since: datetime) -> list[dict]:
    """Events at or after `since`, scanning backward from the append-only tail."""
    if not log.is_file():
        return []
    events = []
    for line in _reverse_lines(log):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = _at(event) if isinstance(event, dict) else None
        if at is not None and at < since:
            break
        if at is not None:
            events.append(event)
    events.reverse()
    return events


def _reverse_lines(path: Path, block_size: int = 64 * 1024) -> Iterator[str]:
    """Yield UTF-8 lines from an append-only file without loading it all."""
    with path.open("rb") as source:
        source.seek(0, 2)
        position = source.tell()
        remainder = b""
        while position:
            size = min(block_size, position)
            position -= size
            source.seek(position)
            chunk = source.read(size) + remainder
            lines = chunk.split(b"\n")
            remainder = lines[0]
            for line in reversed(lines[1:]):
                if line:
                    yield line.decode("utf-8")
        if remainder:
            yield remainder.decode("utf-8")


def _is_noise(event: dict) -> bool:
    # Events logged before `cookie` existed count as noise too: they were
    # never listed before either.
    return (
        event.get("event") == "http_error"
        and event.get("status") in NOISE_STATUSES
        and not event.get("cookie", False)
    )


def _area(event: dict) -> str | None:
    """Area of a failure; None for anything that is not one."""
    name = event.get("event")
    if name == "health_fail":
        return "gameplay"
    if name == "http_error":
        path = event.get("path", "")
        if is_creation_path(path):
            return "creation"
        if path.startswith(("/api/game-health", "/games/")):
            return "gameplay"
        return "other"
    if name == "client_error" and event.get("kind") != "shown":
        if event.get("kind") == "upload" or event.get("page") == "/create":
            return "creation"
        # The home page is the game feed: its errors happen around play.
        if event.get("page") == "/":
            return "gameplay"
        return "other"
    return None


def _signature(event: dict) -> str:
    name = event["event"]
    if name == "http_error":
        path = _ID_SEGMENT.sub("/{id}", event.get("path", ""))
        return f"{event.get('method', '?')} {path} → {event.get('status', '?')}"
    if name == "client_error":
        return f"{event.get('kind', '?')}: {str(event.get('message', ''))[:160]}"
    if name == "health_fail":
        return f"work {event.get('work_id')}: {str(event.get('detail') or event.get('kind'))[:160]}"
    raise ValueError(f"unsupported failure event: {name}")


def _source_key(event: dict) -> str:
    if event.get("person"):
        return event["person"]
    # Logged before person ids existed: the browser string is the best proxy.
    fingerprint = event.get("ua") or event.get("browser") or "?"
    return _LEGACY + hashlib.sha256(fingerprint.encode()).hexdigest()[:6]


def _inferred(event: dict) -> str | None:
    """What the page shows for a failure it does not report itself (see app.js)."""
    name = event["event"]
    if name == "http_error" and event.get("path") == "/api/import-game":
        status = event.get("status")
        if status == 401:
            return "sent to /claim before the message could be read; chosen files and details lost"
        if status == 413:
            return 'dialog says "服务器拒绝了上传，请检查文件大小后重试"; input kept'
        return "dialog shows the server's reason; input kept"
    if name == "health_fail":
        if event.get("kind") == "timeout":
            return "no message from BeePlay; the game area stays as it was"
        return "no message from BeePlay; only what the game itself shows"
    return None


def _saw(event: dict) -> str:
    text = f'"{str(event.get("message", ""))[:160]}"'
    if event.get("next") in _NEXT:
        text += f", {_NEXT[event['next']]}"
    if event.get("lost"):
        text += ", input lost"
    return text


def summarize(events: list[dict]) -> Summary:
    """Failures per area, one entry per person: stuck first, then by count."""
    people: dict[tuple[str, str], Source] = {}
    successes: dict[tuple[str, str], str] = {}
    shown: dict[tuple[str, str], Counter] = {}
    health_plays: set[tuple] = set()
    noise = 0
    for event in events:
        name = event.get("event")
        key = _source_key(event)
        at = event.get("at")
        if name in ("creation_ok", "play_ok"):
            area = "creation" if name == "creation_ok" else "gameplay"
            successes[(area, key)] = max(successes.get((area, key), ""), at or "")
            continue
        if name == "client_error" and event.get("kind") == "shown":
            area = event.get("area") if event.get("area") in AREAS else "other"
            shown.setdefault((area, key), Counter())[_saw(event)] += 1
            continue
        if _is_noise(event):
            noise += 1
            continue
        area = _area(event)
        if area is None:
            continue
        if name == "health_fail" and event.get("session"):
            play = (event.get("work_id"), event.get("artifact"), event["session"])
            if play in health_plays:
                continue
            health_plays.add(play)
        person = people.setdefault((area, key), Source(key, area))
        signature = _signature(event)
        person.failures[signature] += 1
        person.browsers[event.get("browser") or "unknown"] += 1
        if event.get("who"):
            person.who.add(event["who"])
        inferred = _inferred(event)
        if inferred:
            person.inferred.setdefault(signature, inferred)
        person.first_at = person.first_at or at
        person.last_at = at or person.last_at

    areas: dict[str, list[Source]] = {area: [] for area in AREAS}
    for (area, key), person in people.items():
        person.last_success_at = successes.get((area, key))
        person.saw = shown.get((area, key), Counter())
        areas[area].append(person)
    for area_people in areas.values():
        area_people.sort(key=lambda person: (_OUTCOME_ORDER[person.outcome], -person.total))
    return Summary(areas, noise)


def local_time(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.rstrip("Z"))
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%m-%d %H:%M")


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _render_person(person: Source) -> list[str]:
    label = [person.outcome.upper()]
    if person.who:
        label.append(", ".join(sorted(person.who)))
    label.append("/".join(name for name, _ in person.browsers.most_common()))
    if person.in_app_only:
        label.append("in-app only")
    label.append(f"{person.key} (before person ids: same browser, maybe several people)"
                 if person.legacy else person.key)
    if person.first_at and person.last_at:
        label.append(f"{local_time(person.first_at)} → {local_time(person.last_at)}")
    lines = [f"  {' · '.join(label)}"]
    for signature, count in person.failures.most_common():
        lines.append(f"    {count:>3}×  {signature}")
    if not person.saw:
        for text in dict.fromkeys(person.inferred.values()):
            lines.append(f"          saw (inferred): {text}")
    for text, count in person.saw.most_common():
        lines.append(f"          saw: {text}" + (f" (×{count})" if count > 1 else ""))
    return lines


def render(
    summary: Summary, *, since: datetime, now: datetime, window: str, unresolved_uploads: int,
) -> str:
    lines = [f"UX check {local_time(since)} → {local_time(now)} ({window})", ""]
    for area in AREAS:
        area_people = summary.areas[area]
        if area_people:
            outcomes = Counter(person.outcome for person in area_people)
            breakdown = ", ".join(
                f"{outcomes[outcome]} {outcome}" for outcome in _OUTCOME_ORDER if outcomes[outcome]
            )
            failures = sum(person.total for person in area_people)
            lines.append(
                f"{area}: {_plural(len(area_people), 'person', 'people')} ({breakdown}) · "
                f"{_plural(failures, 'failure')}"
            )
        else:
            lines.append(f"{area}: nothing")
        for person in area_people:
            lines.extend(_render_person(person))
        if area == "creation" and unresolved_uploads:
            lines.append(f"  unresolved failed uploads: {unresolved_uploads} (beeplay-ops failed)")
        if area == "other" and summary.noise:
            lines.append(
                f"  noise hidden: {summary.noise} (404/405 from requests without a BeePlay cookie)"
            )
        lines.append("")
    return "\n".join(lines).rstrip()
