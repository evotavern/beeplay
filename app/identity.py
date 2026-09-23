"""The request's claimed identity, shared by the app and its routers."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.repository import COOKIE_NAME, resolve_cookie


def current_identity(
    request: Request, session: Session = Depends(get_session)
) -> tuple[User | None, str]:
    """Resolve the claim cookie once per request and stash it for templates."""
    identity = resolve_cookie(session, request.cookies.get(COOKIE_NAME))
    request.state.identity = identity
    return identity
