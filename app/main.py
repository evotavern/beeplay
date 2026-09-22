from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import PROFILE_TABS, PROFILE_WORKS, works_for

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Beeplay")

app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

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


def discover_context(category: str) -> dict:
    return {"category": category, "works": works_for(category)}


def profile_context(tab: str) -> dict:
    if tab not in PROFILE_TABS:
        tab = "works"
    return {"tab": tab, "empty_title": PROFILE_TABS[tab], "profile_works": PROFILE_WORKS}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return render_view(request, "home")


@app.get("/discover", response_class=HTMLResponse)
def discover(request: Request, category: str = "all") -> HTMLResponse:
    return render_view(request, "discover", **discover_context(category))


@app.get("/create", response_class=HTMLResponse)
def create(request: Request) -> HTMLResponse:
    return render_view(request, "create")


@app.get("/messages", response_class=HTMLResponse)
def messages(request: Request) -> HTMLResponse:
    return render_view(request, "messages")


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, tab: str = "works") -> HTMLResponse:
    return render_view(request, "profile", **profile_context(tab))


@app.get("/partials/works", response_class=HTMLResponse)
def works_partial(request: Request, category: str = "all") -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/work_grid.html", discover_context(category)
    )


@app.get("/partials/profile-works", response_class=HTMLResponse)
def profile_works_partial(request: Request, tab: str = "works") -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/profile_grid.html", profile_context(tab)
    )
