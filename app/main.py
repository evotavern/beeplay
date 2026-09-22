import os
from contextlib import asynccontextmanager
from math import ceil
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.avatars import avatar
from app.data import PROFILE_TABS
from app.db import get_session, init_db
from app.models import User
from app.repository import (
    COOKIE_NAME,
    all_users,
    claim,
    cookie_value,
    discover_works,
    feed_games,
    is_claimed,
    next_free_at,
    profile_works,
    resolve_cookie,
    utcnow,
    works_count,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Unpacked games, one directory per artifact hash. Deployed, this has to live
# in state: ProtectSystem=strict makes the app directory read-only, so the
# mkdir below would fail at startup against BASE_DIR. Same convention as
# BEEPLAY_DB_PATH.
GAMES_DIR = Path(os.environ.get("BEEPLAY_GAMES_DIR", BASE_DIR / "games"))
# Created at import, not in lifespan: app.mount() constructs StaticFiles
# immediately and it raises on a missing directory, which happens before any
# lifespan hook runs. games/ is gitignored, so a fresh checkout has none.
GAMES_DIR.mkdir(parents=True, exist_ok=True)

# A month, so a tester's phone keeps the cookie across the whole event. The
# claim itself expires long before this; the cookie only has to outlive it.
COOKIE_MAX_AGE = 30 * 24 * 60 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def current_identity(
    request: Request, session: Session = Depends(get_session)
) -> tuple[User | None, str]:
    """Resolve the claim cookie once per request and stash it for templates."""
    identity = resolve_cookie(session, request.cookies.get(COOKIE_NAME))
    request.state.identity = identity
    return identity


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
app.mount("/games", StaticFiles(directory=GAMES_DIR), name="games")

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
# Preserve the template's trailing newline; Starlette 1.6 no longer
# forwards env options through the Jinja2Templates constructor.
templates.env.keep_trailing_newline = True
templates.env.globals["avatar"] = avatar


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


def discover_context(session: Session, category: str) -> dict:
    return {"category": category, "works": discover_works(session, category)}


def profile_context(session: Session, user: User, tab: str) -> dict:
    if tab not in PROFILE_TABS:
        tab = "works"
    return {
        "tab": tab,
        "empty_title": PROFILE_TABS[tab],
        "profile_user": user,
        "works_total": works_count(session, user),
        "profile_works": profile_works(session, user) if tab == "works" else [],
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return render_view(request, "home", games=feed_games(session, GAMES_DIR))


@app.get("/discover", response_class=HTMLResponse)
def discover(
    request: Request, category: str = "all", session: Session = Depends(get_session)
) -> HTMLResponse:
    return render_view(request, "discover", **discover_context(session, category))


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
    return templates.TemplateResponse(
        request,
        "base.html",
        {
            "view": "claim",
            "current_user": user,
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


@app.get("/claim/{slug}")
def claim_identity(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    identity: tuple[User | None, str] = Depends(current_identity),
) -> Response:
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
        # No secure flag: the deployment serves plain HTTP on a bare IP, and a
        # secure cookie would simply never be sent back.
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
    request: Request, category: str = "all", session: Session = Depends(get_session)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/work_grid.html", discover_context(session, category)
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


def _bounce_to_claim(request: Request, status: str) -> Response:
    """Send an unidentified visitor to the picker, clearing a dead cookie."""
    target = "/claim?notice=stolen" if status == "stolen" else "/claim"
    response = redirect(request, target)
    if status == "stolen":
        response.delete_cookie(COOKIE_NAME)
    return response
