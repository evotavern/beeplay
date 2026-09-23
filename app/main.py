import hashlib
import os
from functools import lru_cache
import secrets
from contextlib import asynccontextmanager
from math import ceil
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.avatars import avatar
from app.data import PROFILE_TABS
from app.db import get_session, init_db
from app import config, generation, health, ingest
from app.game_imports import GameImportError, pack_zip, read_zip
from app.generation_routes import router as generation_router
from app.identity import current_identity
from app.models import User
from app.repository import (
    COOKIE_NAME,
    all_users,
    claim,
    cookie_value,
    discover_works,
    feed_games,
    is_claimed,
    liked_works,
    next_free_at,
    profile_works,
    record_share,
    record_view,
    saved_count,
    saved_works,
    set_like,
    set_save,
    utcnow,
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

# A month, so a tester's phone keeps the cookie across the whole event. The
# claim itself expires long before this; the cookie only has to outlive it.
COOKIE_MAX_AGE = 30 * 24 * 60 * 60
CSRF_COOKIE_NAME = "beeplay_claim_csrf"
CSRF_TOKEN_BYTES = 32

# The current public deployment is IP-only HTTP. Claims are bearer-token
# authentication, so production must not issue them over that transport. This
# opt-in keeps local HTTP development convenient without silently weakening a
# real deployment.
ALLOW_INSECURE_CLAIMS = os.environ.get("BEEPLAY_ALLOW_INSECURE_CLAIMS") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker = generation.Worker()
    worker.start()
    try:
        yield
    finally:
        worker.close()


def claims_are_secure(request: Request) -> bool:
    """Whether this request may issue or use a bearer claim cookie."""
    return request.url.scheme == "https" or ALLOW_INSECURE_CLAIMS


def csrf_token(request: Request) -> tuple[str, bool]:
    """Return a double-submit CSRF token and whether it needs setting."""
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if token:
        return token, False
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES), True


app = FastAPI(
    title="Beeplay",
    lifespan=lifespan,
    # Applied to every route so base.html can render the claimed user's avatar
    # without each handler having to ask for it.
    dependencies=[Depends(current_identity)],
)

app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

# Development convenience: in production Nginx serves /games/* straight from
# disk, so game files never go through uvicorn's threadpool.
class GameFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Match the in-app sandbox even when an artifact is opened directly.
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


app.mount("/games", GameFiles(directory=GAMES_DIR), name="games")

@lru_cache
def asset(path: str) -> str:
    """URL for a file under assets/, versioned by its contents.

    Nginx lets browsers cache /assets/ for a week, so an unversioned URL keeps
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
templates.env.globals["asset"] = asset
templates.env.globals["load_timeout_s"] = config.LOAD_TIMEOUT_S


def render_view(request: Request, view: str, **context) -> HTMLResponse:
    """Render a view as a bare partial for htmx, or inside the shell otherwise.

    Direct navigation and reloads have no HX-Request header and need the full
    document; an htmx nav click only needs what goes inside #viewport.
    """
    template = f"views/{view}.html" if "HX-Request" in request.headers else "base.html"
    user, _ = getattr(request.state, "identity", (None, "anonymous"))
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
    identity: tuple[User | None, str] = Depends(current_identity),
) -> HTMLResponse:
    user, _ = identity
    return render_view(request, "home", games=feed_games(session, user))


@app.get("/discover", response_class=HTMLResponse)
def discover(
    request: Request,
    category: str = "all",
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> HTMLResponse:
    user, _ = identity
    return render_view(request, "discover", **discover_context(session, category, user))


@app.get("/create", response_class=HTMLResponse)
def create(request: Request) -> HTMLResponse:
    return render_view(request, "create")


@app.get("/messages", response_class=HTMLResponse)
def messages(request: Request) -> HTMLResponse:
    return render_view(request, "messages")


@app.get("/claim", response_class=HTMLResponse)
def claim_grid(
    request: Request,
    notice: str | None = None,
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> HTMLResponse:
    """The identity picker.

    Always a full document, never an htmx partial: it is the one page reached
    by a plain link and by a redirect from anywhere else in the app.
    """
    user, _ = identity
    now = utcnow()
    free_at = next_free_at(session)
    token, set_csrf_cookie = csrf_token(request)
    response = templates.TemplateResponse(
        request,
        "base.html",
        {
            "view": "claim",
            "current_user": user,
            "claims_enabled": claims_are_secure(request),
            "csrf_token": token,
            "notice": notice,
            "identities": [
                {
                    "user": candidate,
                    "claimed": is_claimed(candidate, now),
                    "mine": user is not None and candidate.id == user.id,
                }
                for candidate in all_users(session)
            ],
            "minutes_until_free": (
                ceil((free_at - now).total_seconds() / 60) if free_at else None
            ),
        },
    )
    if set_csrf_cookie:
        response.set_cookie(
            CSRF_COOKIE_NAME,
            token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


@app.post("/claim/{slug}")
def claim_identity(
    slug: str,
    request: Request,
    csrf_token: str = "",
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> Response:
    if not claims_are_secure(request):
        raise HTTPException(status_code=403, detail="Claims require HTTPS")
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_cookie or not secrets.compare_digest(csrf_token, csrf_cookie):
        raise HTTPException(status_code=403, detail="Invalid claim request")

    holder, _ = identity
    token = claim(session, slug, holder)
    if token is None:
        return redirect(request, "/claim?notice=taken")

    response = redirect(request, "/")
    response.set_cookie(
        COOKIE_NAME,
        cookie_value(slug, token),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@app.get("/profile", response_class=HTMLResponse)
def profile(
    request: Request,
    tab: str = "works",
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> Response:
    user, status = identity
    if user is None:
        return _bounce_to_claim(request, status)
    return render_view(request, "profile", **profile_context(session, user, tab))


@app.get("/partials/works", response_class=HTMLResponse)
def works_partial(
    request: Request,
    category: str = "all",
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> HTMLResponse:
    user, _ = identity
    return templates.TemplateResponse(
        request, "partials/work_grid.html", discover_context(session, category, user)
    )


@app.get("/partials/profile-works", response_class=HTMLResponse)
def profile_works_partial(
    request: Request,
    tab: str = "works",
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> Response:
    user, status = identity
    if user is None:
        return _bounce_to_claim(request, status)
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
    identity: tuple[User | None, str] = Depends(current_identity),
) -> JSONResponse:
    """Publish a finished static game from the creator modal, live at once.

    A bundle that fails validation is not simply refused: it is kept, the
    team is alerted, and the uploader is pointed at the hackathon staff.
    """
    user, _ = identity
    if user is None:
        raise HTTPException(status_code=401, detail="先认领一个身份，再上传游戏吧")
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
            session, owner=user, details=details, entries=entries, actor=f"user:{user.slug}"
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
    return JSONResponse({"title": game.title, "artifact": game.artifact_hash})


class HealthReport(BaseModel):
    artifact: str = Field(max_length=64)
    session: str = Field(max_length=64)
    kind: str
    elapsed_ms: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=2000)


class SocialToggle(BaseModel):
    active: bool


class SocialEvent(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)


def _social_not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail="这个游戏已经不在公开游戏流中")


@app.post("/api/works/{work_id}/like")
def update_like(
    work_id: int,
    change: SocialToggle,
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> dict:
    user, _ = identity
    if user is None:
        raise HTTPException(status_code=401, detail="先认领一个身份，再喜欢作品吧")
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
    identity: tuple[User | None, str] = Depends(current_identity),
) -> dict:
    user, _ = identity
    if user is None:
        raise HTTPException(status_code=401, detail="先认领一个身份，再收藏作品吧")
    try:
        active = set_save(session, user, work_id, change.active)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"active": active}


@app.post("/api/works/{work_id}/view")
def create_view(
    work_id: int,
    event: SocialEvent,
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> dict:
    user, _ = identity
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
    identity: tuple[User | None, str] = Depends(current_identity),
) -> dict:
    user, _ = identity
    try:
        count = record_share(session, user, work_id, event.event_id)
    except LookupError as error:
        raise _social_not_found(error) from error
    return {"count": count}


@app.post("/api/game-health", status_code=204)
def game_health(report: HealthReport, session: Session = Depends(get_session)) -> Response:
    """Crash signals forwarded by the game host; see app/health.py."""
    try:
        health.report(
            session,
            artifact_hash=report.artifact,
            session_id=report.session,
            kind=report.kind,
            elapsed_ms=report.elapsed_ms,
            detail=report.detail,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(status_code=204)


def _bounce_to_claim(request: Request, status: str) -> Response:
    """Send an unidentified visitor to the picker, clearing a dead cookie."""
    target = "/claim?notice=stolen" if status == "stolen" else "/claim"
    response = redirect(request, target)
    if status == "stolen":
        response.delete_cookie(COOKIE_NAME)
    return response


app.include_router(generation_router)


@app.middleware("http")
async def private_generation_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/generations"):
        response.headers["Cache-Control"] = "no-store"
    return response
