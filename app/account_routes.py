"""Profile editing, photo, password, login, logout and staff reset links.

Every write here is JSON (or, for the photo, multipart) from our own pages and
checked with same_origin: a cross-site form must not be able to log a visitor
into someone else's account or change their profile.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import accounts, events, photos
from app.avatars import user_avatar
from app.db import get_session
from app.identity import cookies_are_secure, current_user, same_origin, set_session_cookie
from app.models import User

router = APIRouter()


def _views():
    # Rendering lives in main, which imports this module to include the
    # router, so it can only be imported once a request arrives.
    from app import main

    return main


def signed_in(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "请先打开个人页")
    return user


def _refuse(error: accounts.AccountError) -> HTTPException:
    return HTTPException(422, str(error))


# --- pages ---------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next_url: str = Query("/profile", alias="next"),
    user: User | None = Depends(current_user),
    session: Session = Depends(get_session),
):
    main = _views()
    return main.render_view(
        request,
        "login",
        next_url=main.local_path(next_url),
        # Logging in folds this device's automatic account in; say so.
        device_has_activity=(
            user is not None and user.password_hash is None and not accounts.is_empty(session, user)
        ),
    )


@router.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, token: str = "", session: Session = Depends(get_session)):
    target = accounts.reset_target(session, token) if token else None
    return _views().render_view(request, "reset", token=token, reset_user=target)


@router.get("/partials/profile-editor", response_class=HTMLResponse)
def profile_editor(request: Request, prompt: bool = False, user: User = Depends(signed_in)):
    return _views().templates.TemplateResponse(
        request, "partials/profile_editor.html", {"current_user": user, "prompt": prompt}
    )


@router.get("/partials/password-editor", response_class=HTMLResponse)
def password_editor(request: Request, user: User = Depends(signed_in)):
    return _views().templates.TemplateResponse(
        request, "partials/password_editor.html", {"current_user": user}
    )


# --- writes ----------------------------------------------------------------------


class ProfileChange(BaseModel):
    name: str = Field(max_length=200)
    bio: str = Field(default="", max_length=1000)
    avatar_fill: str = Field(max_length=6)


class PasswordChange(BaseModel):
    password: str = Field(max_length=1000)
    handle: str | None = Field(default=None, max_length=100)
    current_password: str | None = Field(default=None, max_length=1000)


class Login(BaseModel):
    handle: str = Field(max_length=100)
    password: str = Field(max_length=1000)


class Reset(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1000)


def _account_payload(user: User) -> dict:
    return {
        "name": user.name,
        "handle": user.slug,
        "bio": user.bio,
        "avatar": user_avatar(user),
        "has_password": user.password_hash is not None,
    }


@router.post("/api/account/profile", dependencies=[Depends(same_origin)])
def update_profile(body: ProfileChange, user: User = Depends(signed_in), session: Session = Depends(get_session)):
    try:
        accounts.update_profile(session, user, name=body.name, bio=body.bio, avatar_fill=body.avatar_fill)
    except accounts.AccountError as error:
        raise _refuse(error) from error
    return _account_payload(user)


@router.post("/api/account/photo", dependencies=[Depends(same_origin)])
def upload_photo(
    photo: UploadFile = File(...),
    user: User = Depends(signed_in),
    session: Session = Depends(get_session),
):
    raw = photo.file.read(photos.MAX_BYTES + 1)
    try:
        user.avatar_path = photos.store(raw)
    except photos.PhotoError as error:
        raise HTTPException(422, str(error)) from error
    session.commit()
    events.log_event("avatar_uploaded", who=f"u{user.id}", slug=user.slug, file=user.avatar_path)
    return _account_payload(user)


@router.delete("/api/account/photo", dependencies=[Depends(same_origin)])
def remove_photo(user: User = Depends(signed_in), session: Session = Depends(get_session)):
    user.avatar_path = None
    session.commit()
    return _account_payload(user)


@router.post("/api/account/password", dependencies=[Depends(same_origin)])
def set_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(signed_in),
    session: Session = Depends(get_session),
):
    try:
        accounts.set_password(
            session, user, request.state.device,
            password=body.password, handle=body.handle, current_password=body.current_password,
        )
    except accounts.AccountError as error:
        raise _refuse(error) from error
    events.log_event("account_password_set", who=f"u{user.id}", slug=user.slug)
    return _account_payload(user)


def _sign_in(request: Request, response: Response, session: Session, target: User) -> bool:
    """Put this device on target's account. Returns whether anything was merged.

    The device's own account is folded in when it has no password (it cannot
    be reached any other way); a real account is merely signed out here.
    """
    current = request.state.user
    device = request.state.device
    merged = False
    if current is not None and current.id != target.id:
        if current.password_hash is None:
            merged = not accounts.is_empty(session, current)
            accounts.merge(session, current, target)
            events.log_event("account_merged", source=f"u{current.id}", who=f"u{target.id}")
        elif device is not None:
            accounts.end_session(session, device)
    elif current is not None and device is not None:
        accounts.end_session(session, device)
    set_session_cookie(request, response, accounts.start_session(session, target))
    return merged


@router.post("/api/login", dependencies=[Depends(same_origin)])
def login(body: Login, request: Request, response: Response, session: Session = Depends(get_session)):
    if not cookies_are_secure(request):
        raise HTTPException(403, "需要 HTTPS 连接")
    ip = request.client.host if request.client else "unknown"
    try:
        target = accounts.authenticate(session, body.handle, body.password, ip=ip)
    except accounts.AccountError as error:
        raise _refuse(error) from error
    merged = _sign_in(request, response, session, target)
    events.log_event("account_login", who=f"u{target.id}", merged=merged)
    return {"merged": merged, **_account_payload(target)}


@router.post("/api/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response, user: User = Depends(signed_in), session: Session = Depends(get_session)):
    if user.password_hash is None:
        # Without a password there would be no way back into this account.
        raise HTTPException(409, "先设置密码，再退出登录")
    if request.state.device is not None:
        accounts.end_session(session, request.state.device)
    response.delete_cookie(accounts.COOKIE_NAME)
    return {"ok": True}


@router.post("/api/reset", dependencies=[Depends(same_origin)])
def reset(body: Reset, request: Request, response: Response, session: Session = Depends(get_session)):
    if not cookies_are_secure(request):
        raise HTTPException(403, "需要 HTTPS 连接")
    try:
        target = accounts.consume_reset(session, body.token, body.password)
    except accounts.AccountError as error:
        raise _refuse(error) from error
    # consume_reset signed every device out, including possibly this one.
    request.state.device = None
    if request.state.user is not None and request.state.user.id == target.id:
        request.state.user = None
    _sign_in(request, response, session, target)
    events.log_event("account_reset", who=f"u{target.id}")
    return _account_payload(target)
