from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Beeplay")

app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
# Keeps rendered output byte-identical to the source template.
templates.env.keep_trailing_newline = True


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
