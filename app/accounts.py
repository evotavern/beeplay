"""Accounts, device sessions, passwords and merging.

An account appears the first time someone needs one (a like, a save, a
creation, their own profile) and lives in this device's session cookie.
Setting a password locks the handle and lets the same person log in on
another device; logging in there folds that device's own throwaway account
into theirs, because in-app browsers (WeChat, QQ, Douyin) keep separate
cookies and people will end up with one account per app otherwise.
"""

import hashlib
import re
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import AVATAR_FILLS, RESERVED_HANDLES
from app.models import (
    FailedUpload,
    Generation,
    User,
    UserSession,
    Work,
    WorkLike,
    WorkSave,
    WorkShare,
    WorkView,
    utcnow,
)

COOKIE_NAME = "beeplay_session"
# The old claim cookie. Nothing reads it; responses clear it on sight.
LEGACY_COOKIE_NAME = "beeplay_user"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

# last_seen_at is only rewritten once it is this stale: every htmx partial
# would otherwise be a write, and SQLite has a single writer.
TOUCH_INTERVAL = timedelta(minutes=5)

RESET_TTL = timedelta(hours=24)

HANDLE_PATTERN = re.compile(r"[a-z0-9_]{3,20}")
NAME_MAX = 20
BIO_MAX = 120
PASSWORD_MIN = 6
PASSWORD_MAX = 128

_hasher = PasswordHasher()
# Verified against when the handle does not exist, so a miss costs as long as
# a wrong password and does not reveal which handles are taken.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


class AccountError(ValueError):
    """A refusal worth showing the person as it is."""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- creation and sessions ------------------------------------------------


def create_account(session: Session) -> User:
    """A new account with an automatic name, handle and colour."""
    for _ in range(20):
        number = secrets.randbelow(900_000) + 100_000
        user = User(
            slug=f"bee{number}",
            name=f"小蜜蜂 #{number % 10_000:04d}",
            avatar_fill=secrets.choice(AVATAR_FILLS),
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            continue
        return user
    raise RuntimeError("could not find a free automatic handle")


def start_session(session: Session, user: User) -> str:
    """A new device session; returns the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    session.add(UserSession(user_id=user.id, token_hash=token_hash(token)))
    session.commit()
    return token


def resolve(session: Session, token: str | None) -> tuple[User | None, UserSession | None]:
    if not token:
        return None, None
    device = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if device is None:
        return None, None
    user = session.get(User, device.user_id)
    if user is None or not user.loginable:
        return None, None
    now = utcnow()
    if device.last_seen_at <= now - TOUCH_INTERVAL:
        device.last_seen_at = now
        session.commit()
    return user, device


def end_session(session: Session, device: UserSession) -> None:
    session.execute(delete(UserSession).where(UserSession.id == device.id))
    session.commit()


def end_other_sessions(session: Session, user: User, keep: UserSession | None) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user.id)
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep.id)
    session.execute(stmt)


def is_empty(session: Session, user: User) -> bool:
    """Whether an automatic account has anything worth keeping."""
    for model in (Work, WorkLike, WorkSave, WorkView, Generation):
        if session.scalar(select(model.user_id).where(model.user_id == user.id).limit(1)) is not None:
            return False
    return True


# --- profile ----------------------------------------------------------------


def clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise AccountError("名字不能为空")
    if len(name) > NAME_MAX:
        raise AccountError(f"名字最多 {NAME_MAX} 个字")
    return name


def clean_bio(value: str) -> str:
    bio = " ".join(value.split())
    if len(bio) > BIO_MAX:
        raise AccountError(f"简介最多 {BIO_MAX} 个字")
    return bio


def clean_fill(value: str) -> str:
    if value not in AVATAR_FILLS:
        raise AccountError("请选择一个头像颜色")
    return value


def update_profile(session: Session, user: User, *, name: str, bio: str, avatar_fill: str) -> None:
    user.name = clean_name(name)
    user.bio = clean_bio(bio)
    user.avatar_fill = clean_fill(avatar_fill)
    session.commit()


def take_profile_prompt(session: Session, user: User) -> bool:
    """Whether to ask for a name and photo now: once, after a first publish."""
    if user.profile_prompted:
        return False
    user.profile_prompted = True
    session.commit()
    return True


def clean_handle(value: str) -> str:
    handle = value.strip().lstrip("@").lower()
    if not HANDLE_PATTERN.fullmatch(handle):
        raise AccountError("用户名需要 3–20 位，只能用小写字母、数字和下划线")
    if handle in RESERVED_HANDLES:
        raise AccountError("这个用户名已被保留，换一个吧")
    return handle


# --- passwords ----------------------------------------------------------------


def _check_password(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise AccountError(f"密码至少 {PASSWORD_MIN} 位")
    if len(password) > PASSWORD_MAX:
        raise AccountError("密码太长了")


def _verify(stored: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def set_password(
    session: Session,
    user: User,
    device: UserSession | None,
    *,
    password: str,
    handle: str | None = None,
    current_password: str | None = None,
) -> None:
    """Set or change the password. The first time also picks and locks the handle.

    Changing an existing password needs the current one and signs every other
    device out.
    """
    _check_password(password)
    if user.password_hash is not None:
        if not _verify(user.password_hash, current_password or ""):
            raise AccountError("当前密码不对")
        end_other_sessions(session, user, device)
    if not user.handle_locked:
        chosen = clean_handle(handle if handle is not None else user.slug)
        if chosen != user.slug and session.scalar(select(User.id).where(User.slug == chosen)):
            raise AccountError("这个用户名已经有人用了")
        user.slug = chosen
        user.handle_locked = True
    user.password_hash = _hasher.hash(password)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise AccountError("这个用户名已经有人用了") from error


class FailureLimiter:
    """Counts failed logins per key in a sliding window; successes are free."""

    def __init__(self, *, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        queued = self._failures[key]
        while queued and queued[0] <= now - self.window_s:
            queued.popleft()
        return queued

    def blocked(self, key: str, *, now: float | None = None) -> bool:
        with self._lock:
            return len(self._prune(key, monotonic() if now is None else now)) >= self.limit

    def fail(self, key: str, *, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        with self._lock:
            self._prune(key, current).append(current)


# A whole venue can share one IP, so that limit is generous; a single handle
# is what a guesser targets.
handle_failures = FailureLimiter(limit=10, window_s=15 * 60)
ip_failures = FailureLimiter(limit=50, window_s=15 * 60)


def authenticate(session: Session, handle: str, password: str, *, ip: str) -> User:
    key = handle.strip().lstrip("@").lower()
    if handle_failures.blocked(key) or ip_failures.blocked(ip):
        raise AccountError("尝试次数太多了，请 15 分钟后再试")
    user = session.scalar(select(User).where(User.slug == key, User.loginable))
    if user is None or not _verify(user.password_hash, password):
        handle_failures.fail(key)
        ip_failures.fail(ip)
        raise AccountError("用户名或密码不对")
    return user


# --- merging ------------------------------------------------------------------


def merge(session: Session, source: User, target: User) -> None:
    """Fold a device's automatic account into the one just logged into.

    Likes and saves that both accounts have count once. The source account
    and its sessions are deleted; the caller starts a session for target.
    """
    if source.id == target.id:
        return
    for model in (WorkLike, WorkSave):
        rows = session.execute(
            select(model.work_id, model.created_at).where(model.user_id == source.id)
        ).all()
        for work_id, created_at in rows:
            session.execute(
                sqlite_insert(model)
                .values(user_id=target.id, work_id=work_id, created_at=created_at)
                .on_conflict_do_nothing()
            )
        session.execute(delete(model).where(model.user_id == source.id))
    session.execute(
        update(Work).where(Work.user_id == source.id).values(user_id=target.id, author=target.name)
    )
    for model in (WorkView, WorkShare, FailedUpload, Generation):
        session.execute(
            update(model).where(model.user_id == source.id).values(user_id=target.id)
        )
    session.execute(delete(UserSession).where(UserSession.user_id == source.id))
    session.execute(delete(User).where(User.id == source.id))
    session.commit()


# --- staff password reset -------------------------------------------------------


def issue_reset(session: Session, slug: str) -> str:
    user = session.scalar(select(User).where(User.slug == slug, User.loginable))
    if user is None:
        raise AccountError(f"no account @{slug}")
    token = secrets.token_urlsafe(24)
    user.reset_token_hash = token_hash(token)
    user.reset_expires_at = utcnow() + RESET_TTL
    session.commit()
    return token


def reset_target(session: Session, token: str, now: datetime | None = None) -> User | None:
    user = session.scalar(select(User).where(User.reset_token_hash == token_hash(token)))
    if user is None or user.reset_expires_at is None:
        return None
    if user.reset_expires_at <= (now or utcnow()):
        return None
    return user


def consume_reset(session: Session, token: str, password: str) -> User:
    """Set a new password from a reset link and sign every device out."""
    user = reset_target(session, token)
    if user is None:
        raise AccountError("这个重置链接已失效，请再找工作人员要一个")
    _check_password(password)
    user.password_hash = _hasher.hash(password)
    user.handle_locked = True
    user.reset_token_hash = None
    user.reset_expires_at = None
    end_other_sessions(session, user, None)
    session.commit()
    return user
