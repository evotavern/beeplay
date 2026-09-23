"""Who the request is from, shared by the app and its routers."""
import os

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import accounts
from app.db import get_session
from app.models import User

# The public deployment is HTTPS-only. A session cookie is a bearer
# credential, so it is never issued over plain HTTP unless local development
# opts in. (The name predates accounts; deploy scripts refer to it.)
ALLOW_INSECURE_COOKIES = os.environ.get("BEEPLAY_ALLOW_INSECURE_CLAIMS") == "1"


def cookies_are_secure(request: Request) -> bool:
    return request.url.scheme == "https" or ALLOW_INSECURE_COOKIES


def current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    """Resolve the session cookie once per request and stash it for templates."""
    user, device = accounts.resolve(session, request.cookies.get(accounts.COOKIE_NAME))
    request.state.user = user
    request.state.device = device
    return user


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        accounts.COOKIE_NAME,
        token,
        max_age=accounts.COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def ensure_user(request: Request, response: Response, session: Session) -> User:
    """The request's account, creating one (and its cookie) if there is none."""
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    if not cookies_are_secure(request):
        raise HTTPException(status_code=403, detail="需要 HTTPS 连接")
    user = accounts.create_account(session)
    token = accounts.start_session(session, user)
    set_session_cookie(request, response, token)
    request.state.user = user
    request.state.device = None
    return user


def account(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> User:
    """Dependency form of ensure_user, for endpoints that return plain data."""
    return ensure_user(request, response, session)


def same_origin(request: Request) -> None:
    """Refuse cross-site writes. SameSite=Lax alone would still let another
    site log a visitor into an attacker's account."""
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Invalid origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Invalid origin")
