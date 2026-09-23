"""Crash reports from players' browsers, and hiding games that keep crashing.

The browser sends: start (host mounted the iframe), loaded (the game's
reporter saw window.load), error (the reporter caught an exception), and
timeout (the host waited LOAD_TIMEOUT_S and never heard "loaded").

Reports are not authenticated; a flood of fake ones can hide a game, and an
operator restores it with `beeplay-ops status <id> live`.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import browsers, config, events, ingest
from app.models import HealthEvent, Work, utcnow

KINDS = ("start", "loaded", "error", "timeout")


@dataclass
class Summary:
    plays: int
    failed: int
    recent_errors: list[HealthEvent]


def _counts_as_failure(event: HealthEvent) -> bool:
    if event.kind == "timeout":
        return True
    return event.kind == "error" and (event.elapsed_ms or 0) <= config.ERROR_WINDOW_S * 1000


def summary(session: Session, work: Work) -> Summary:
    """Plays and failed plays of the current artifact inside the crash window."""
    since = utcnow() - timedelta(minutes=config.CRASH_WINDOW_MIN)
    window = list(
        session.scalars(
            select(HealthEvent)
            .where(
                HealthEvent.work_id == work.id,
                HealthEvent.artifact_hash == work.artifact_hash,
                HealthEvent.at >= since,
            )
            .order_by(HealthEvent.at.desc(), HealthEvent.id.desc())
        )
    )
    plays = {event.session_id for event in window}
    failed = {event.session_id for event in window if _counts_as_failure(event)}
    errors = [event for event in window if event.kind in ("error", "timeout")]
    return Summary(plays=len(plays), failed=len(failed), recent_errors=errors[:10])


def report(
    session: Session,
    *,
    artifact_hash: str,
    session_id: str,
    kind: str,
    elapsed_ms: int | None = None,
    detail: str | None = None,
    user_agent: str | None = None,
) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    work = session.scalar(
        select(Work).where(Work.artifact_hash == artifact_hash, Work.status != "deleted")
    )
    if work is None:
        # An old version still open in someone's tab, or a made-up hash.
        return
    event = HealthEvent(
        work_id=work.id,
        artifact_hash=artifact_hash,
        session_id=session_id[:64],
        kind=kind,
        elapsed_ms=elapsed_ms,
        detail=(detail or "")[:500] or None,
    )
    session.add(event)
    session.commit()

    if kind not in ("error", "timeout"):
        return
    counted = _counts_as_failure(event)
    events.log_event(
        "health_fail" if counted else "health_error_late",
        work_id=work.id, artifact=artifact_hash, session=session_id,
        kind=kind, elapsed_ms=elapsed_ms, detail=event.detail,
        **browsers.fields(user_agent),
    )
    if counted and work.status == "live":
        _hide_if_crashing(session, work)


def _hide_if_crashing(session: Session, work: Work) -> None:
    current = summary(session, work)
    if current.failed < config.CRASH_MIN_FAILURES:
        return
    if current.failed < config.CRASH_RATIO * current.plays:
        return
    ingest.set_status(session, work, "hidden", actor="system")
    events.log_event(
        "auto_hidden", work_id=work.id, artifact=work.artifact_hash,
        plays=current.plays, failed=current.failed,
    )
    last = current.recent_errors[0].detail if current.recent_errors else None
    events.alert(
        f"💥 自动下架：{work.title}（work {work.id}）\n"
        f"最近 {config.CRASH_WINDOW_MIN} 分钟 {current.plays} 次游玩里 {current.failed} 次崩溃\n"
        f"最后一个错误：{last}\n"
        f"查看：beeplay-ops health {work.id}；修好后：beeplay-ops replace {work.id} <目录或zip>"
    )
