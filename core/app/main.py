"""Core server. Run from core/: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import config, tts
from .hazards import all_phrases, detector
from .mirror import mirror
from .session import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("core")

STATIC = Path(__file__).resolve().parent.parent / "static"
state: dict = {"phones": 0, "session": None}   # session = most recent phone connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(detector.load)
    asyncio.create_task(tts.pregenerate(all_phrases()))   # hazard audio, cached in the background
    yield


app = FastAPI(title="core", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "phones_connected": state["phones"],
        "hazards": detector.model is not None,
        "stt": bool(config.CARTESIA_API_KEY),
        "tts": bool(config.CARTESIA_API_KEY and config.CARTESIA_VOICE_ID),
        "claude": bool(config.ANTHROPIC_API_KEY),
        "jev": bool(config.TYPESAFE_API_KEY),
        "memory_url": config.MEMORY_URL,
        "browser_url": config.BROWSER_URL,
    }


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    state["phones"] += 1
    await mirror.emit("phone", connected=True)
    log.info("phone connected")
    session = Session(ws)
    state["session"] = session
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        state["phones"] -= 1
        if state["session"] is session:
            state["session"] = None
        await mirror.emit("phone", connected=False)
        log.info("phone disconnected")


@app.websocket("/mirror/ws")
async def mirror_ws(ws: WebSocket):
    await mirror.add(ws)
    try:
        while True:
            # The mirror page can type an utterance (backup for when the mic misbehaves on stage).
            data = json.loads(await ws.receive_text())
            session = state["session"]
            if data.get("text") and session:
                session.spawn(session.handle_utterance(data["text"]))
    except WebSocketDisconnect:
        mirror.remove(ws)


@app.get("/")
@app.get("/mirror")
async def mirror_page():
    return FileResponse(STATIC / "mirror.html")
