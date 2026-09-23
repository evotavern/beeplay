"""The one path every game takes into Beeplay, from the web or the ops CLI.

Validation and unpacking live in game_imports; this module owns what
happens around them: the database row, the audit trail, logs and alerts.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import config, events
from app.game_imports import install_folder
from app.models import STATUSES, FailedUpload, User, Work

ARTS = ("art-one", "art-two", "art-three", "art-four")


class DetailsError(ValueError):
    """The form was filled in wrong. Not a broken bundle, so nothing is kept."""


@dataclass(frozen=True)
class GameDetails:
    title: str
    category: str
    emoji: str
    art: str
    description: str | None


def validate_details(
    *, title: str, category: str, emoji: str, art: str, description: str | None
) -> GameDetails:
    title, category, emoji = title.strip(), category.strip(), emoji.strip()
    if not title:
        raise DetailsError("给游戏起个名字吧")
    if not category:
        raise DetailsError("给游戏选一个分类吧，随便写也行")
    if not emoji:
        raise DetailsError("挑一个表情当游戏图标吧")
    if art not in ARTS:
        raise DetailsError("选一个封面风格吧")
    return GameDetails(
        title=title[:120],
        category=category[:24],
        emoji=emoji[:8],
        art=art,
        description=(description or "").strip()[:200] or None,
    )


def _game_url(work: Work) -> str:
    return f"{config.PUBLIC_URL}/games/{work.artifact_hash}/index.html"


def publish(
    session: Session,
    *,
    owner: User,
    details: GameDetails,
    entries: list[tuple[str, bytes]],
    actor: str,
    status: str = "live",
    commit: bool = True,
) -> Work:
    """Install a bundle and put it in the feed. Raises GameImportError if broken."""
    artifact = install_folder(entries, config.GAMES_DIR)
    work = Work(
        title=details.title,
        author=owner.name,
        category=details.category,
        emoji=details.emoji,
        art=details.art,
        description=details.description,
        collection="feed",
        artifact_hash=artifact,
        user_id=owner.id,
        status=status,
    )
    session.add(work)
    session.flush()
    events.record(
        session, work, actor=actor, kind="created",
        after={"status": status, "artifact": artifact, "title": details.title},
    )
    if commit:
        session.commit()
        announce(work, owner)
    return work


def announce(work: Work, owner: User) -> None:
    """Alert the team about a new game. With publish(commit=False), call this
    after committing, so nothing is announced that could still roll back."""
    events.alert(f"🆕 新游戏：{work.title}（{owner.slug}，{work.status}）\n{_game_url(work)}")


def set_status(session: Session, work: Work, status: str, *, actor: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if work.status == status:
        return
    before = work.status
    work.status = status
    events.record(
        session, work, actor=actor, kind="status_changed",
        before={"status": before}, after={"status": status},
    )
    session.commit()


def replace(
    session: Session, work: Work, *, entries: list[tuple[str, bytes]], actor: str
) -> None:
    """Serve a new version. The old directory stays on disk, unreferenced.

    A new directory rather than an overwrite, because Nginx tells browsers to
    cache /games/ as immutable for a year. A hidden game comes back live:
    replacing it is how staff deliver a fix.
    """
    artifact = install_folder(entries, config.GAMES_DIR)
    before = work.artifact_hash
    work.artifact_hash = artifact
    events.record(
        session, work, actor=actor, kind="artifact_replaced",
        before={"artifact": before}, after={"artifact": artifact},
    )
    session.commit()
    if work.status == "hidden":
        set_status(session, work, "live", actor=actor)


def capture_failure(
    session: Session, *, owner: User | None, details: GameDetails, raw_zip: bytes, error: str
) -> FailedUpload:
    """Keep a bundle that failed validation so an operator can fix and insert it."""
    config.FAILED_DIR.mkdir(parents=True, exist_ok=True)
    stored = config.FAILED_DIR / f"{uuid.uuid4().hex}.zip"
    stored.write_bytes(raw_zip)
    failed = FailedUpload(
        user_id=owner.id if owner else None,
        title=details.title,
        category=details.category,
        emoji=details.emoji,
        art=details.art,
        description=details.description,
        error=error,
        stored_path=str(stored),
    )
    session.add(failed)
    session.commit()
    slug = owner.slug if owner else None
    events.log_event(
        "upload_failed", failed_id=failed.id, slug=slug, title=details.title,
        error=error, stored=str(stored),
    )
    events.alert(
        f"🚨 上传失败：{details.title}（{slug}）\n原因：{error}\n"
        f"原始文件：{stored}\n修好后：beeplay-ops import <修好的目录或zip> --from-failed {failed.id}"
    )
    return failed
