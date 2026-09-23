"""What users ran into since the last check, for `beeplay-ops ux`.

Reads the failure events in events.jsonl (http_error, client_error from the
page reporter, health_fail and auto_hidden from the game reporter) and groups
them by area and by browser. Creation and gameplay are in scope; everything
else is only counted.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import browsers

AREAS = ("creation", "gameplay")
DEFAULT_WINDOW = timedelta(hours=24)

_ID_SEGMENT = re.compile(r"/\d+(?=/|$)")


@dataclass
class Group:
    area: str
    signature: str
    count: int = 0
    browsers: Counter = field(default_factory=Counter)
    last_at: str | None = None

    @property
    def in_app_only(self) -> bool:
        return bool(self.browsers) and set(self.browsers) <= browsers.IN_APP


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
    """Events at or after `since` (naive UTC, like the log)."""
    if not log.is_file():
        return []
    events = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = _at(event) if isinstance(event, dict) else None
        if at is not None and at >= since:
            events.append(event)
    return events


def _area(event: dict) -> str | None:
    name = event.get("event")
    if name in ("health_fail", "auto_hidden"):
        return "gameplay"
    if name == "http_error":
        path = event.get("path", "")
        if path.startswith("/api/import-game") or path == "/create":
            return "creation"
        if path.startswith("/api/game-health"):
            return "gameplay"
        return "other"
    if name == "client_error":
        if event.get("kind") == "upload" or event.get("page") == "/create":
            return "creation"
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
    return f"work {event.get('work_id')} auto-hidden ({event.get('failed')}/{event.get('plays')} plays failed)"


def summarize(events: list[dict]) -> dict[str, list[Group]]:
    """Failure groups per area ("creation", "gameplay", "other"), biggest first."""
    groups: dict[tuple[str, str], Group] = {}
    for event in events:
        area = _area(event)
        if area is None:
            continue
        signature = _signature(event)
        group = groups.setdefault((area, signature), Group(area, signature))
        group.count += 1
        group.browsers[event.get("browser") or "unknown"] += 1
        group.last_at = event.get("at", group.last_at)
    summary: dict[str, list[Group]] = {area: [] for area in (*AREAS, "other")}
    for group in groups.values():
        summary[group.area].append(group)
    for area_groups in summary.values():
        area_groups.sort(key=lambda group: -group.count)
    return summary


def local_time(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.rstrip("Z"))
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%m-%d %H:%M")


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def render(
    summary: dict[str, list[Group]], *, since: datetime, now: datetime, window: str,
    unresolved_uploads: int,
) -> str:
    lines = [f"UX check {local_time(since)} → {local_time(now)} ({window})", ""]
    for area in AREAS:
        area_groups = summary[area]
        if area_groups:
            total = sum(group.count for group in area_groups)
            lines.append(f"{area}: {total} failures in {len(area_groups)} groups")
        else:
            lines.append(f"{area}: nothing")
        for group in area_groups:
            seen = ", ".join(f"{name} {count}" for name, count in group.browsers.most_common())
            notes = [seen]
            if group.in_app_only:
                notes.append("in-app only")
            if group.last_at:
                notes.append(f"last {local_time(group.last_at)}")
            lines.append(f"  {group.count:>3}×  {group.signature}")
            lines.append(f"        {' · '.join(notes)}")
        if area == "creation" and unresolved_uploads:
            lines.append(f"  unresolved failed uploads: {unresolved_uploads} (beeplay-ops failed)")
        lines.append("")
    other = sum(group.count for group in summary["other"])
    lines.append(f"other: {other} failure{'s' if other != 1 else ''} outside creation and gameplay, not in scope")
    return "\n".join(lines)
