import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.data import PROFILE_TABS
from app.db import get_session, init_db
from app.game_imports import GameImportError, install_folder, install_zip
from app.repository import discover_works, feed_games, profile_works, register_imported_game

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Beeplay", lifespan=lifespan)

app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

# Development convenience: in production Nginx serves /games/* straight from
# disk, so game files never go through uvicorn's threadpool.
app.mount("/games", StaticFiles(directory=GAMES_DIR), name="games")

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
# Preserve the template's trailing newline; Starlette 1.6 no longer
# forwards env options through the Jinja2Templates constructor.
templates.env.keep_trailing_newline = True


def render_view(request: Request, view: str, **context) -> HTMLResponse:
    """Render a view as a bare partial for htmx, or inside the shell otherwise.

    Direct navigation and reloads have no HX-Request header and need the full
    document; an htmx nav click only needs what goes inside #viewport.
    """
    template = f"views/{view}.html" if "HX-Request" in request.headers else "base.html"
    return templates.TemplateResponse(request, template, {"view": view, **context})


def discover_context(session: Session, category: str) -> dict:
    return {"category": category, "works": discover_works(session, category)}


def profile_context(session: Session, tab: str) -> dict:
    if tab not in PROFILE_TABS:
        tab = "works"
    return {
        "tab": tab,
        "empty_title": PROFILE_TABS[tab],
        "profile_works": profile_works(session) if tab == "works" else [],
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


@app.get("/profile", response_class=HTMLResponse)
def profile(
    request: Request, tab: str = "works", session: Session = Depends(get_session)
) -> HTMLResponse:
    return render_view(request, "profile", **profile_context(session, tab))


@app.get("/partials/works", response_class=HTMLResponse)
def works_partial(
    request: Request, category: str = "all", session: Session = Depends(get_session)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/work_grid.html", discover_context(session, category)
    )


@app.get("/partials/profile-works", response_class=HTMLResponse)
def profile_works_partial(
    request: Request, tab: str = "works", session: Session = Depends(get_session)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/profile_grid.html", profile_context(session, tab)
    )


@app.post("/api/import-game", response_class=JSONResponse)
async def import_game(
    title: str = Form(""),
    bundle: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    paths: list[str] | None = Form(None),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Import a finished static game through the existing creator modal."""
    try:
        if bundle is not None:
            artifact = install_zip(await bundle.read(), GAMES_DIR)
            fallback_title = Path(bundle.filename or "新小游戏").stem
        else:
            uploaded = files or []
            relative_paths = paths or []
            if len(uploaded) != len(relative_paths):
                raise GameImportError("游戏文件路径不完整")
            artifact = install_folder(
                [(path, await file.read()) for file, path in zip(uploaded, relative_paths)],
                GAMES_DIR,
            )
            fallback_title = Path(relative_paths[0]).parts[0] if relative_paths else "新小游戏"
    except GameImportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    game = register_imported_game(
        session, artifact_hash=artifact, title=(title.strip() or fallback_title)[:120]
    )
    return JSONResponse({"title": game.title, "artifact": artifact})
