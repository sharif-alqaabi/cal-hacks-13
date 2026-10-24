"""Browser service HTTP layer (port 8002). Run from browser/:  uv run uvicorn app:app --port 8002

The request and response shapes are core's contract, copied from core/contracts/browser.py: change them there first.
Fake mode: BROWSER_FAKE=1 runs a scripted Gmail instead of Chrome (no keys needed).
Judges' trace: http://localhost:8002/trace
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import agents
import config
import goals
import runner
import tracelog
import work

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("browser")


class TaskReq(BaseModel):        # POST /task
    goal: str


class TaskResp(BaseModel):
    task_id: str
    say: str                     # read-back of the draft, ready to speak
    needs_confirm: bool


class ConfirmReq(BaseModel):     # POST /confirm
    task_id: str
    yes: bool


class SayResp(BaseModel):        # response for /confirm and /work
    say: str


class WorkReq(BaseModel):        # POST /work (P2)
    utterance: str
    jpeg_b64: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.FAKE:
        # Attaching to Chrome can wait on its "Allow remote debugging?" prompt: never on the request path.
        agents.reconnect_in_background()
    log.info("browser service up (fake=%s, contacts=%s)", config.FAKE, list(goals.contacts()))
    yield
    await asyncio.get_running_loop().run_in_executor(runner.EXEC, runner.store.close_current)


app = FastAPI(title="browser", lifespan=lifespan)


def show(path: str, req: BaseModel) -> None:
    body = {k: (f"<{len(v)} base64 chars>" if k == "jpeg_b64" else v) for k, v in req.model_dump().items()}
    log.info("%s %s", path, body)


@app.get("/health")
async def health():
    try:
        chrome = await asyncio.wait_for(asyncio.to_thread(agents.chrome_ready), 1.0)
    except Exception:
        chrome = False
    return {
        "ok": True,
        "fake": config.FAKE,
        "chrome": chrome,
        "keys": {"typesafe": bool(config.TYPESAFE_API_KEY), "text_model": bool(config.TEXT_MODEL_API_KEY),
                 "anthropic": bool(config.ANTHROPIC_API_KEY)},
        "endpoints": {"jev": config.TYPESAFE_BASE_URL, "claude": config.ANTHROPIC_BASE_URL},
        "contacts": sorted(goals.contacts()),
        "pending": len(runner.store.pending),
        "prefill": config.GMAIL_PREFILL,
        "verify_cancel": config.VERIFY_CANCEL,
        "log_dir": str(config.LOG_DIR),
    }


@app.post("/task", response_model=TaskResp)
async def task(req: TaskReq):
    show("/task", req)
    r = TaskResp(**await runner.run_task(req.goal))
    log.info("/task -> %s", r.model_dump())
    return r


@app.post("/confirm", response_model=SayResp)
async def confirm(req: ConfirmReq):
    show("/confirm", req)
    r = SayResp(say=await runner.confirm(req.task_id, req.yes))
    log.info("/confirm -> %s", r.model_dump())
    return r


@app.post("/work", response_model=SayResp)
async def work_check(req: WorkReq):
    show("/work", req)
    try:
        return SayResp(say=await work.check(req.utterance, req.jpeg_b64))
    except Exception:
        log.exception("work failed")
        raise HTTPException(503, "work failed")   # core turns this into "The laptop assistant isn't available"


@app.get("/trace")
async def trace_page():
    return FileResponse(config.HERE / "static" / "trace.html")


@app.get("/trace/latest")
async def trace_latest(since: int = 0):
    return tracelog.since(since)
