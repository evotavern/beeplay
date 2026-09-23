"""Which player a logged event belongs to, without logging who they are.

`beeplay-ops ux` groups failures by person. A claimed identity is not a
person (it is released after two idle hours and someone else can take it),
so the key is the client IP plus User-Agent, keyed with a server-only secret
and the UTC date: stable for a day, unlinkable across days, and the raw IP is
never written anywhere.
"""

import hashlib
import hmac
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request

from app import config

_keys: dict[Path, bytes] = {}
_lock = threading.Lock()


def _secret() -> bytes:
    path = config.EVENTS_LOG.with_name("person-key")
    with _lock:
        if path not in _keys:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                _keys[path] = path.read_bytes()
            else:
                secret = os.urandom(32)
                with os.fdopen(descriptor, "wb") as target:
                    target.write(secret)
                _keys[path] = secret
        return _keys[path]


def person_id(ip: str, user_agent: str | None, *, day: str | None = None) -> str:
    day = day or datetime.now(timezone.utc).date().isoformat()
    message = f"{day}|{ip}|{user_agent or ''}".encode()
    return "p-" + hmac.new(_secret(), message, hashlib.sha256).hexdigest()[:8]


def fields(request: Request) -> dict:
    """The person fields every logged event about a player carries.

    `cookie` says whether the request came from someone who has used the
    site; a 404 without it is a scanner, not a player.
    """
    ip = request.client.host if request.client else "unknown"
    identity = getattr(request.state, "identity", None)
    user = identity[0] if identity else None
    result = {
        "person": person_id(ip, request.headers.get("user-agent")),
        "cookie": any(name.startswith("beeplay") for name in request.cookies),
    }
    if user is not None:
        result["who"] = user.slug
    return result
