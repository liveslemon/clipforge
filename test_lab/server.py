"""ClipForge Test Lab web server — upload a video from your laptop and watch every module analyse it."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from modules.module_07_highlight_scorer import NichePreset

from .engine import MODULES, RUNS_DIR, VIDEO_EXTS, LabSession, ROOT
from .pytest_runner import run_module_tests

app = FastAPI(title="ClipForge Test Lab")
PAGE = Path(__file__).with_name("page.html")
UPLOADS = RUNS_DIR / "_uploads"
STATE: dict = {"session": None}


def session() -> LabSession:
    if STATE["session"] is None:
        raise HTTPException(400, "Load a video first (upload one or paste a path).")
    return STATE["session"]


def open_session(path: Path) -> dict:
    if path.suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(400, f"'{path.suffix}' doesn't look like a video ({', '.join(sorted(VIDEO_EXTS))}).")
    prev = STATE["session"]
    if prev and prev.video == path.resolve():
        return prev.info(full=True)  # same file: keep cached results
    STATE["session"] = LabSession(path)
    return STATE["session"].info(full=True)


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.read_text().replace("/*__STATIC__*/", "")


@app.get("/api/setup")
def setup():
    """Which API keys / tools are configured (re-reads .env so edits show up without a restart)."""
    from modules.config import capability_report, reload_settings
    reload_settings()
    return capability_report()


@app.get("/api/state")
def state():
    s = STATE["session"]
    return {"modules": MODULES, "session": s.info(full=True) if s else None,
            "presets": [p.value for p in NichePreset], "preset": s.preset.value if s else "GAMING"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / Path(file.filename or "upload.mp4").name
    with open(dest, "wb") as f:
        while chunk := await file.read(8 * 1024 * 1024):
            f.write(chunk)
    return open_session(dest)


@app.post("/api/use-path")
def use_path(path: str = Body(..., embed=True)):
    p = Path(path.strip().strip("'\"")).expanduser()
    if not p.is_file():
        raise HTTPException(404, f"No file at {p}")
    return open_session(p)


@app.post("/api/chat")
async def upload_chat(file: Optional[UploadFile] = File(None)):
    s = session()
    if file is None:
        s.set_chat(None)
        return s.info()
    dest = s.dir / ("chat_" + Path(file.filename or "chat.txt").name)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    s.set_chat(dest)
    return s.info()


@app.get("/api/recent")
def recent():
    """Videos already on this laptop in the usual places, newest first."""
    home = Path.home()
    places = [UPLOADS, ROOT / "studio_uploads", ROOT / "demo_output", home / "Movies", home / "Downloads",
              home / "Desktop", home / "Videos"]
    found = []
    for d in places:
        try:
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS and "_proxy_" not in p.name and not p.name.startswith("render_"):
                    st = p.stat()
                    found.append({"path": str(p), "name": p.name, "dir": str(d).replace(str(home), "~"),
                                  "mb": round(st.st_size / 1e6, 1), "mtime": st.st_mtime})
        except (OSError, PermissionError):
            continue
    return sorted(found, key=lambda x: -x["mtime"])[:40]


@app.post("/api/context")
def set_context(context: str = Body(..., embed=True)):
    s = session()
    s.set_context(context)
    return s.info()


@app.post("/api/preset")
def set_preset(preset: str = Body(..., embed=True)):
    s = session()
    with s.lock:
        s.preset = NichePreset(preset)
        s.cache.pop("candidates", None)
        s.cache.pop("renders", None)
    return {"preset": s.preset.value}


@app.post("/api/run/{n}")
def run(n: int):
    if n not in MODULES:
        raise HTTPException(404, "Unknown module")
    return session().run(n)


@app.get("/api/progress")
def progress():
    s = STATE["session"]
    return {"progress": s.progress if s else ""}


@app.post("/api/pytest/{n}")
def pytest(n: int):
    if n not in MODULES:
        raise HTTPException(404, "Unknown module")
    return run_module_tests(n)


@app.get("/api/source")
def source():
    return FileResponse(session().video)


@app.get("/files/{run_id}/{rel:path}")
def files(run_id: str, rel: str):
    base = (RUNS_DIR / run_id).resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target)
