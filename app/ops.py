"""Operator CLI, run over SSH on the server:

    beeplay-ops list                         # every game, with status and owner
    beeplay-ops failed                       # uploads waiting for a fix
    beeplay-ops import DIR_OR_ZIP --from-failed ID
    beeplay-ops import DIR_OR_ZIP --owner beeplay --title … --category … --emoji … [--unlisted]
    beeplay-ops replace WORK_ID DIR_OR_ZIP   # ship a fix; a hidden game comes back live
    beeplay-ops status WORK_ID live|hidden|unlisted|deleted
    beeplay-ops health WORK_ID               # recent plays and errors
    beeplay-ops history WORK_ID              # the audit trail
    beeplay-ops ux [--every 60] [--since 2h] # what users hit since the last check
    beeplay-ops refresh-reporter             # add the crash reporter to older games
    beeplay-ops migrate                      # schema + seed; release.sh runs it

SSH access is the only authentication. Every change is audited as ops:<user>.
"""

import argparse
import getpass
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, db, health, ingest, ux
from app.game_imports import REPORTER_MARKER, REPORTER_VERSION, GameImportError, read_zip
from app.models import STATUSES, FailedUpload, User, Work, WorkEvent, utcnow


def _actor() -> str:
    return "ops:" + (os.environ.get("SUDO_USER") or getpass.getuser())


def _entries(source: Path) -> list[tuple[str, bytes]]:
    if source.is_dir():
        return [
            (path.relative_to(source).as_posix(), path.read_bytes())
            for path in sorted(source.rglob("*"))
            if path.is_file()
        ]
    return read_zip(source.read_bytes())


def _work(session: Session, work_id: int) -> Work:
    work = session.get(Work, work_id)
    if work is None:
        raise SystemExit(f"no work {work_id}")
    return work


def _owner_slug(session: Session, work: Work) -> str:
    owner = session.get(User, work.user_id) if work.user_id else None
    return owner.slug if owner else "-"


def cmd_list(session: Session, args) -> None:
    stmt = select(Work).where(Work.collection == "feed").order_by(Work.created_at.desc())
    if args.status:
        stmt = stmt.where(Work.status == args.status)
    for work in session.scalars(stmt):
        print(
            f"{work.id:>4}  {work.status:<8}  {_owner_slug(session, work):<8}  "
            f"{work.created_at:%m-%d %H:%M}  {work.artifact_hash}  {work.title}"
        )


def cmd_failed(session: Session, args) -> None:
    stmt = select(FailedUpload).order_by(FailedUpload.created_at.desc())
    if not args.all:
        stmt = stmt.where(FailedUpload.resolved_work_id.is_(None))
    for failed in session.scalars(stmt):
        owner = session.get(User, failed.user_id) if failed.user_id else None
        resolved = f"→ work {failed.resolved_work_id}" if failed.resolved_work_id else "open"
        print(
            f"{failed.id:>4}  {failed.created_at:%m-%d %H:%M}  {owner.slug if owner else '-':<8}  "
            f"{resolved:<12}  {failed.title}\n      {failed.error}\n      {failed.stored_path}"
        )


def cmd_import(session: Session, args) -> None:
    failed = session.get(FailedUpload, args.from_failed) if args.from_failed else None
    if args.from_failed and failed is None:
        raise SystemExit(f"no failed upload {args.from_failed}")

    if failed is not None:
        owner = session.get(User, failed.user_id)
        source = Path(args.source or failed.stored_path)
        details = ingest.validate_details(
            title=args.title or failed.title,
            category=args.category or failed.category,
            emoji=args.emoji or failed.emoji,
            art=args.art or failed.art,
            description=args.description if args.description is not None else failed.description,
        )
    else:
        if not (args.source and args.owner and args.title and args.category and args.emoji):
            raise SystemExit("import needs SOURCE, --owner, --title, --category and --emoji")
        owner = session.scalar(select(User).where(User.slug == args.owner))
        source = Path(args.source)
        details = ingest.validate_details(
            title=args.title, category=args.category, emoji=args.emoji,
            art=args.art or "art-one", description=args.description,
        )
    if owner is None:
        raise SystemExit("owner not found")

    work = ingest.publish(
        session, owner=owner, details=details, entries=_entries(source), actor=_actor(),
        status="unlisted" if args.unlisted else "live",
    )
    if failed is not None:
        failed.resolved_work_id = work.id
        session.commit()
    print(f"work {work.id} {work.status}: {config.PUBLIC_URL}/games/{work.artifact_hash}/index.html")


def cmd_replace(session: Session, args) -> None:
    work = _work(session, args.work_id)
    ingest.replace(session, work, entries=_entries(Path(args.source)), actor=_actor())
    print(f"work {work.id} {work.status}: now {work.artifact_hash}")


def cmd_status(session: Session, args) -> None:
    work = _work(session, args.work_id)
    ingest.set_status(session, work, args.status, actor=_actor())
    print(f"work {work.id} is {work.status}")


def cmd_health(session: Session, args) -> None:
    work = _work(session, args.work_id)
    current = health.summary(session, work)
    print(
        f"work {work.id} ({work.status}) {work.title}\n"
        f"last {config.CRASH_WINDOW_MIN} min: {current.plays} plays, {current.failed} failed"
    )
    for event in current.recent_errors:
        print(f"  {event.at:%H:%M:%S}  {event.kind:<7} {event.elapsed_ms}ms  {event.detail}")


def cmd_history(session: Session, args) -> None:
    work = _work(session, args.work_id)
    rows = session.scalars(
        select(WorkEvent).where(WorkEvent.work_id == work.id).order_by(WorkEvent.id)
    )
    for row in rows:
        print(f"{row.at:%m-%d %H:%M:%S}  {row.actor:<14} {row.kind:<18} {row.before} → {row.after}")


def cmd_refresh_reporter(session: Session, args) -> None:
    works = session.scalars(
        select(Work).where(Work.artifact_hash.is_not(None), Work.status != "deleted")
    )
    for work in list(works):
        directory = config.GAMES_DIR / work.artifact_hash
        index = directory / "index.html"
        if not index.is_file():
            print(f"work {work.id}: {index} missing, skipped")
            continue
        if REPORTER_VERSION in index.read_bytes():
            continue
        ingest.replace(session, work, entries=_entries(directory), actor=_actor())
        print(f"work {work.id}: reporter added, now {work.artifact_hash}")


def _duration(text: str) -> str:
    ux.parse_duration(text)  # argparse turns the ValueError into a usage error
    return text


def _ux_state() -> Path:
    # Next to the events log, so the service user can write it and it
    # survives releases; deliberately not in the repo.
    return config.EVENTS_LOG.with_name("ux-last-run")


def cmd_ux(session: Session, args) -> None:
    now = utcnow()
    state = _ux_state()
    last = datetime.fromisoformat(state.read_text().strip()) if state.is_file() else None

    if args.every is not None and last is not None:
        due = last + timedelta(minutes=args.every)
        if now < due:
            print(f"last check {ux.minutes(now - last)} min ago; "
                  f"next check due in {ux.minutes(due - now) + 1} min")
            return

    if args.since:
        since, window = now - ux.parse_duration(args.since), f"last {args.since}"
    elif last is not None:
        since, window = last, f"since last check, {ux.minutes(now - last)} min ago"
    else:
        since, window = now - ux.DEFAULT_WINDOW, "last 24h; never checked before"

    unresolved = len(session.scalars(
        select(FailedUpload.id).where(FailedUpload.resolved_work_id.is_(None))
    ).all())
    summary = ux.summarize(ux.read_events(config.EVENTS_LOG, since=since))
    print(ux.render(summary, since=since, now=now, window=window, unresolved_uploads=unresolved))

    if not args.no_mark:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(now.isoformat())


def cmd_migrate(session: Session, args) -> None:
    db.init_db()
    print("database is at the latest schema")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beeplay-ops", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list")
    listing.add_argument("--status", choices=STATUSES)
    listing.set_defaults(run=cmd_list)

    failed = commands.add_parser("failed")
    failed.add_argument("--all", action="store_true", help="include resolved ones")
    failed.set_defaults(run=cmd_failed)

    importing = commands.add_parser("import")
    importing.add_argument("source", nargs="?", help="game folder or zip")
    importing.add_argument("--from-failed", type=int, metavar="ID")
    importing.add_argument("--owner", help="slug, e.g. bee-3 or beeplay")
    importing.add_argument("--title")
    importing.add_argument("--category")
    importing.add_argument("--emoji")
    importing.add_argument("--art", choices=ingest.ARTS)
    importing.add_argument("--description")
    importing.add_argument("--unlisted", action="store_true", help="test game, link only")
    importing.set_defaults(run=cmd_import)

    replacing = commands.add_parser("replace")
    replacing.add_argument("work_id", type=int)
    replacing.add_argument("source")
    replacing.set_defaults(run=cmd_replace)

    status = commands.add_parser("status")
    status.add_argument("work_id", type=int)
    status.add_argument("status", choices=STATUSES)
    status.set_defaults(run=cmd_status)

    for name, run in (("health", cmd_health), ("history", cmd_history)):
        sub = commands.add_parser(name)
        sub.add_argument("work_id", type=int)
        sub.set_defaults(run=run)

    checking = commands.add_parser("ux", help="what users ran into since the last check")
    checking.add_argument("--since", metavar="DURATION", type=_duration,
                          help="window instead of since-last-check, e.g. 30m, 2h, 1d")
    checking.add_argument("--every", type=int, metavar="MINUTES",
                          help="do nothing if the last check is more recent than this")
    checking.add_argument("--no-mark", action="store_true", help="don't record this as a check")
    checking.set_defaults(run=cmd_ux)

    commands.add_parser("refresh-reporter").set_defaults(run=cmd_refresh_reporter)
    commands.add_parser("migrate").set_defaults(run=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with db.SessionLocal() as session:
        try:
            args.run(session, args)
        except (GameImportError, ingest.DetailsError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
