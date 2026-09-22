from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import PROFILE_WORKS, WORKS

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Beeplay")

app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
# Preserve the template's trailing newline; Starlette 1.6 no longer
# forwards env options through the Jinja2Templates constructor.
templates.env.keep_trailing_newline = True


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"works": WORKS, "profile_works": PROFILE_WORKS},
    )
