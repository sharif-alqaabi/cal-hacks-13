"""Memory service HTTP layer (port 8001). Run from memory/:  uvicorn app:app --port 8001

The request and response shapes are core's contract, copied from core/contracts/memory.py: change them there first.
Test mode: MEMORY_TEST_SCENES=1 reads scene text from mock JPEGs, MEMORY_ALLOW_RESET=1 enables POST /reset.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from service import TEST_SCENES, THUMB_DIR, Service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("memory")
RESET_ALLOWED = os.getenv("MEMORY_ALLOW_RESET", "").strip().lower() in {"1", "true", "yes", "on"}


class IngestReq(BaseModel):      # POST /ingest -> 202
    ts: float
    jpeg_b64: str


class RecallReq(BaseModel):      # POST /recall
    question: str
    jpeg_b64: Optional[str] = None  # live frame for present-tense "who is this" face match


class RecallResp(BaseModel):
    answer: str                  # one ready-to-speak sentence
    ts: Optional[float] = None
    thumb_url: Optional[str] = None


class RememberReq(BaseModel):    # POST /remember: label is what the wearer said
    label: str
    ts: float
    jpeg_b64: str


class AlertReq(BaseModel):       # POST /alert
    kind: Literal["lost", "help"]
    note: str = ""


class OkResp(BaseModel):
    ok: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.svc = Service()
    await app.state.svc.start()
    yield
    await app.state.svc.close()


THUMB_DIR.mkdir(exist_ok=True)  # the static mount needs the folder before the lifespan runs
app = FastAPI(title="memory", lifespan=lifespan)
app.mount("/thumbs", StaticFiles(directory=THUMB_DIR), name="thumbs")


def svc() -> Service:
    return app.state.svc


def show(path: str, req: BaseModel) -> None:
    """One line per request: the JSON core sent, with the image reduced to its size."""
    body = {k: (f"<{len(v)} base64 chars>" if k == "jpeg_b64" and v is not None else v) for k, v in req.model_dump().items()}
    log.info("%s %s", path, body)


@app.get("/health")
async def health():
    return {"ok": True, "pending": svc().pending, "moments": len(svc().moments), "test_scenes": TEST_SCENES}


@app.post("/ingest", status_code=202)
async def ingest(req: IngestReq):
    show("/ingest", req)
    svc().ingest(req.ts, req.jpeg_b64)
    return Response(status_code=202)


@app.post("/recall", response_model=RecallResp)
async def recall(req: RecallReq):
    show("/recall", req)
    try:
        return RecallResp(**await svc().recall(req.question, req.jpeg_b64))
    except Exception:
        log.exception("recall failed")
        raise HTTPException(503, "recall failed")  # core turns this into "Memory isn't available right now"


@app.post("/remember", response_model=OkResp)
async def remember(req: RememberReq):
    show("/remember", req)
    try:
        return OkResp(ok=await svc().remember(req.label, req.ts, req.jpeg_b64))
    except Exception:
        log.exception("remember failed")
        raise HTTPException(503, "remember failed")


@app.post("/alert", response_model=OkResp)
async def alert(req: AlertReq):
    show("/alert", req)
    try:
        await svc().alert(req.kind, req.note)
        return OkResp(ok=True)
    except Exception:
        log.exception("alert failed")
        raise HTTPException(503, "alert failed")


@app.post("/reset", response_model=OkResp)
async def reset():
    if not RESET_ALLOWED:
        raise HTTPException(403, "set MEMORY_ALLOW_RESET=1 to enable /reset")
    await svc().reset()
    return OkResp(ok=True)


# The family dashboard (built with `npm run build` in dashboard/). Mounted last so it never shadows an API route;
# served from here so the page and the thumbnails share one origin.
DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
if DASHBOARD_DIST.is_dir():
    app.mount("/", StaticFiles(directory=DASHBOARD_DIST, html=True), name="dashboard")
