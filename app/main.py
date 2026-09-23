import hashlib
import html
import re
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.avatars import avatar, user_avatar
from app.data import AVATAR_FILLS, PROFILE_TABS
from app.db import get_session, init_db
from app import accounts, browsers, config, events, generation, health, ingest, people, ux
from app.account_routes import router as account_router
from app.game_imports import GameImportError, pack_zip, read_zip
from app.generation_routes import router as generation_router
from app.identity import account, current_user, ensure_user
from app.models import User
from app.repository import (
    add_comment,
    comment_payload,
    comments_for_work,
    discover_works,
    feed_games,
    liked_works,
    likes_received,
    profile_works,
    public_works,
    record_share,
    record_view,
    saved_count,
    saved_works,
    set_like,
    set_comment_like,
    set_follow,
    set_save,
    user_by_handle,
    viewed_works,
    works_count,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Unpacked games, one directory per artifact hash. Deployed, this has to live
# in state: ProtectSystem=strict makes the app directory read-only, so the
# mkdir below would fail at startup against BASE_DIR. Same convention as
# BEEPLAY_DB_PATH.
GAMES_DIR = config.GAMES_DIR
# Created at import, not in lifespan: app.mount() constructs StaticFiles
# immediately and it raises on a missing directory, which happens before any
# lifespan hook runs. games/ is gitignored, so a fresh checkout has none.
GAMES_DIR.mkdir(parents=True, exist_ok=True)
# Same reason as GAMES_DIR: StaticFiles needs it to exist at import.
config.AVATARS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker = generation.Worker()
    worker.start()
    try:
        yield
    finally:
        worker.close()


def local_path(target: str) -> str:
    """Where to land after a login: a path on this site, never another host.

    "//host" and "/\\host" are protocol-relative in browsers, so a bare
    leading slash is not enough to stay on this origin. Browsers also drop
    tabs and newlines from URLs, which would turn "/\\t/host" into "//host".
    """
    if any(char <= " " for char in target):
        return "/"
    if target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return "/"


app = FastAPI(
    title="Beeplay",
    lifespan=lifespan,
    # Applied to every route so base.html can render the signed-in user's
    # avatar without each handler having to ask for it.
    dependencies=[Depends(current_user)],
)


@app.middleware("http")
async def log_failed_requests(request: Request, call_next) -> Response:
    """Every 4xx/5xx and every crash lands in events.jsonl for `beeplay-ops ux`.

    Only the path is kept: query strings can carry tokens (a password-reset link).
    """
    where = {"method": request.method, "path": request.url.path}
    client = browsers.fields(request.headers.get("user-agent"))
    try:
        response = await call_next(request)
    except Exception as error:
        await run_in_threadpool(
            events.log_event, "http_error", **where, status=500,
            error=repr(error)[:500], **client, **people.fields(request),
        )
        raise
    if response.status_code >= 400:
        await run_in_threadpool(
            events.log_event, "http_error", **where, status=response.status_code,
            **client, **people.fields(request),
        )
    elif ux.is_creation_success(request.method, request.url.path):
        # Lets the check tell a player who got through from one still stuck.
        await run_in_threadpool(
            events.log_event, "creation_ok", **where, **client, **people.fields(request)
        )
    return response


app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

# Development convenience: in production Caddy serves /games/* straight from
# disk, so game files never go through uvicorn's threadpool.
class GameFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Match the in-app sandbox even when an artifact is opened directly.
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # The sandbox's opaque origin fetches the game's own files from
        # Origin: null; see deploy/beeplay.caddy.
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


app.mount("/games", GameFiles(directory=GAMES_DIR), name="games")


class AvatarFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


# Development convenience again: Caddy serves /avatars/* from disk.
app.mount("/avatars", AvatarFiles(directory=config.AVATARS_DIR), name="avatars")

@lru_cache
def asset(path: str) -> str:
    """URL for a file under assets/, versioned by its contents.

    Caddy lets browsers cache /assets/ for a week, so an unversioned URL keeps
    returning visitors on the previous release's JavaScript after a deploy.
    Hashed once per process, i.e. once per release.
    """
    digest = hashlib.sha256((BASE_DIR / "assets" / path).read_bytes()).hexdigest()[:12]
    return f"/assets/{path}?v={digest}"


templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
# Preserve the template's trailing newline; Starlette 1.6 no longer
# forwards env options through the Jinja2Templates constructor.
templates.env.keep_trailing_newline = True
templates.env.globals["avatar"] = avatar
templates.env.globals["user_avatar"] = user_avatar
templates.env.globals["avatar_fills"] = AVATAR_FILLS
templates.env.globals["asset"] = asset
templates.env.globals["load_timeout_s"] = config.LOAD_TIMEOUT_S


@lru_cache
def display_title(artifact: str | None, stored: str) -> str:
    """Recover legacy rows that accidentally stored the entry filename."""
    if stored.strip().lower() not in {"index.html", "index.htm"} or not artifact:
        return stored
    entry = GAMES_DIR / artifact / "index.html"
    try:
        source = entry.read_text(errors="ignore")[:64_000]
    except OSError:
        return stored
    match = re.search(r"<title[^>]*>(.*?)</title>", source, re.IGNORECASE | re.DOTALL)
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip() if match else stored


templates.env.globals["display_title"] = display_title


def render_view(request: Request, view: str, **context) -> HTMLResponse:
    """Render a view as a bare partial for htmx, or inside the shell otherwise.

    Direct navigation and reloads have no HX-Request header and need the full
    document; an htmx nav click only needs what goes inside #viewport.
    """
    template = f"views/{view}.html" if "HX-Request" in request.headers else "base.html"
    user = getattr(request.state, "user", None)
    return templates.TemplateResponse(
        request, template, {"view": view, "current_user": user, **context}
    )


def redirect(request: Request, url: str) -> Response:
    """Send the browser elsewhere, whichever way it asked.

    htmx swaps a redirect's body into #viewport instead of navigating, which
    would push a whole document inside <main> and leave the address bar on the
    old URL. HX-Redirect is the header that makes it a real navigation.
    """
    if "HX-Request" in request.headers:
        return HTMLResponse("", headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def discover_context(session: Session, category: str, user: User | None = None) -> dict:
    works = discover_works(session, category, user)
    return {
        "category": category,
        "works": works,
        "featured_work": works[0] if works else None,
    }


def profile_context(session: Session, user: User, tab: str) -> dict:
    if tab not in PROFILE_TABS:
        tab = "works"
    loaders = {
        "works": profile_works,
        "likes": liked_works,
        "saved": saved_works,
        "history": viewed_works,
    }
    works = loaders[tab](session, user)
    return {
        "tab": tab,
        "empty_title": PROFILE_TABS[tab] if not works else None,
        "profile_user": user,
        "works_total": works_count(session, user),
        "saved_total": saved_count(session, user),
        "profile_works": works,
    }


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> HTMLResponse:
    return render_view(request, "home", games=feed_games(session, user))


@app.get("/discover", response_class=HTMLResponse)
def discover(
    request: Request,
    category: str = "all",
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> HTMLResponse:
    return render_view(request, "discover", **discover_context(session, category, user))


@app.get("/create", response_class=HTMLResponse)
def create(request: Request) -> HTMLResponse:
    return render_view(request, "create")


@app.get("/messages", response_class=HTMLResponse)
def messages(request: Request) -> HTMLResponse:
    return render_view(request, "messages")


@app.get("/claim")
def claim_grid() -> Response:
    """The old identity picker. Printed links still point here."""
    return RedirectResponse("/profile", status_code=303)


def with_cookies(source: Response, target: Response) -> Response:
    """Copy Set-Cookie from FastAPI's injected response onto one we built."""
    for name, value in source.raw_headers:
        if name == b"set-cookie":
            target.raw_headers.append((name, value))
    return target


@app.get("/profile", response_class=HTMLResponse)
def profile(
    request: Request,
    response: Response,
    tab: str = "works",
    session: Session = Depends(get_session),
) -> Response:
    """Your own profile. Opening it is one of the things that makes an account."""
    user = ensure_user(request, response, session)
    return with_cookies(
        response, render_view(request, "profile", **profile_context(session, user, tab))
    )


@app.get("/u/{slug}", response_class=HTMLResponse)
def public_profile(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    viewer: User | None = Depends(current_user),
) -> HTMLResponse:
    owner = user_by_handle(session, slug)
    if owner is None:
        raise HTTPException(status_code=404, detail="没有这个用户")
    works = public_works(session, owner, viewer)
    return render_view(
        request,
        "user",
        profile_user=owner,
        profile_works=works,
        works_total=len(works),
        likes_total=likes_received(session, owner),
        is_me=viewer is not None and viewer.id == owner.id,
    )


@app.get("/partials/works", response_class=HTMLResponse)
def works_partial(
    request: Request,
    category: str = "all",
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/work_grid.html", discover_context(session, category, user)
    )


@app.get("/partials/profile-works", response_class=HTMLResponse)
def profile_works_partial(
    request: Request,
    tab: str = "works",
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> Response:
    if user is None:
        return redirect(request, "/profile")
    return templates.TemplateResponse(
        request, "partials/profile_grid.html", profile_context(session, user, tab)
    )


@app.post("/api/import-game", response_class=JSONResponse)
def import_game(
    title: str = Form(""),
    category: str = Form(""),
    emoji: str = Form(""),
    art: str = Form(""),
    description: str = Form(""),
    bundle: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    paths: list[str] | None = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    """Publish a finished static game from the creator modal, live at once.

    A bundle that fails validation is not simply refused: it is kept, the
    team is alerted, and the uploader is pointed at the hackathon staff.
    """
    try:
        details = ingest.validate_details(
            title=title, category=category, emoji=emoji, art=art, description=description
        )
    except ingest.DetailsError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    raw_zip: bytes | None = None
    entries: list[tuple[str, bytes]] = []
    try:
        if bundle is not None:
            raw_zip = bundle.file.read()
            entries = read_zip(raw_zip)
        else:
            uploaded, relative_paths = files or [], paths or []
            entries = [(path, file.file.read()) for file, path in zip(uploaded, relative_paths)]
            if len(uploaded) != len(relative_paths):
                raise GameImportError("游戏文件路径不完整")
        game = ingest.publish(
            session, owner=user, details=details, entries=entries, actor=f"user:{user.id}"
        )
    except GameImportError as error:
        ingest.capture_failure(
            session,
            owner=user,
            details=details,
            raw_zip=raw_zip if raw_zip is not None else pack_zip(entries),
            error=str(error),
        )
        raise HTTPException(
            status_code=422,
            detail=f"这个游戏包有点闹脾气 🐝（{error}）。别慌，去找黑客松工作人员，我们帮你把它送上首页！",
        ) from error
    return {
        "title": game.title,
        "artifact": game.artifact_hash,
        "ask_profile": accounts.take_profile_prompt(session, user),
    }


class HealthReport(BaseModel):
    artifact: str = Field(max_length=64)
    session: str = Field(max_length=64)
    kind: str
    elapsed_ms: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=2000)


class SocialToggle(BaseModel):
    active: bool


class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class SocialEvent(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)


def _social_not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail="这个游戏已经不在公开游戏流中")


@app.post("/api/works/{work_id}/like")
def update_like(
    work_id: int,
    change: SocialToggle,
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    try:
        active, count = set_like(session, user, work_id, change.active)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"active": active, "count": count}


@app.post("/api/works/{work_id}/save")
def update_save(
    work_id: int,
    change: SocialToggle,
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    try:
        active = set_save(session, user, work_id, change.active)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"active": active}


@app.post("/api/users/{user_id}/follow")
def update_follow(
    user_id: int,
    change: SocialToggle,
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    try:
        active = set_follow(session, user, user_id, change.active)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"active": active}


@app.get("/api/works/{work_id}/comments")
def get_comments(
    work_id: int,
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict:
    try:
        comments = comments_for_work(session, user, work_id)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"comments": comments}


@app.post("/api/works/{work_id}/comments", status_code=201)
def create_comment(
    work_id: int,
    payload: CommentCreate,
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="评论不能为空")
    try:
        comment = add_comment(session, user, work_id, payload.content)
    except LookupError as error:
        raise _social_not_found(error) from error
    return comment_payload(comment, user, likes=0, liked=False)


@app.post("/api/comments/{comment_id}/like")
def update_comment_like(
    comment_id: int,
    change: SocialToggle,
    session: Session = Depends(get_session),
    user: User = Depends(account),
) -> dict:
    try:
        active, count = set_comment_like(session, user, comment_id, change.active)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"active": active, "count": count}


@app.post("/api/works/{work_id}/view")
def create_view(
    work_id: int,
    event: SocialEvent,
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict:
    try:
        count = record_view(session, user, work_id, event.event_id)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"count": count}


@app.post("/api/works/{work_id}/share")
def create_share(
    work_id: int,
    event: SocialEvent,
    session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict:
    try:
        count = record_share(session, user, work_id, event.event_id)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"count": count}


@app.post("/api/game-health", status_code=204)
def game_health(
    report: HealthReport, request: Request, session: Session = Depends(get_session)
) -> Response:
    """Crash signals forwarded by the game host; see app/health.py."""
    try:
        health.report(
            session,
            artifact_hash=report.artifact,
            session_id=report.session,
            kind=report.kind,
            elapsed_ms=report.elapsed_ms,
            detail=report.detail,
            user_agent=request.headers.get("user-agent"),
            person=people.fields(request),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(status_code=204)


class ClientError(BaseModel):
    """A failure the page itself saw; sent by assets/js/page-reporter.js."""

    # "shown" is not a failure of its own: it records the message a failure
    # put in front of the player and what happened to them next.
    kind: Literal["error", "rejection", "script", "upload", "shown"]
    message: str = Field(max_length=1000)
    area: Literal["creation", "gameplay"] | None = None
    next: Literal["stayed", "redirected", "closed"] | None = None
    lost: bool | None = None
    status: int | None = None
    page: str | None = Field(default=None, max_length=300)
    source: str | None = Field(default=None, max_length=500)
    line: int | None = None
    column: int | None = None
    stack: str | None = Field(default=None, max_length=4000)


@app.post("/api/client-error", status_code=204)
def client_error(report: ClientError, request: Request) -> Response:
    """Log only, like game health: unauthenticated, so nothing acts on it."""
    client = request.client.host if request.client else "unknown"
    if not events.client_error_limiter.allow(client):
        # Stay quiet: a 429 would be written by log_failed_requests and let a
        # flood consume the same disk this limit protects.
        return Response(status_code=204)
    events.log_event(
        "client_error",
        **report.model_dump(exclude_none=True),
        **browsers.fields(request.headers.get("user-agent")),
        **people.fields(request),
    )
    return Response(status_code=204)


app.include_router(generation_router)
app.include_router(account_router)


@app.middleware("http")
async def private_generation_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/generations", "/api/account")):
        response.headers["Cache-Control"] = "no-store"
    # The pre-accounts claim cookie means nothing now; drop it on sight.
    if accounts.LEGACY_COOKIE_NAME in request.cookies:
        response.delete_cookie(accounts.LEGACY_COOKIE_NAME)
    return response
