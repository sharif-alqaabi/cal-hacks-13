"""Core server. Run from core/: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from contracts.stream import AudioMsg, PttMsg, TextMsg
from . import config, llm, net, stt, tts
from .clients import browser, memory
from .hazards import all_phrases, detector
from .mirror import mirror
from .session import FIXED_PHRASES, Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("core")

STATIC = Path(__file__).resolve().parent.parent / "static"
# phones: live phone sessions, newest last. headless: used whenever no phone is connected.
state: dict = {"phones": [], "headless": None, "memory_up": False, "browser_up": False}


def active_session() -> Session:
    if state["headless"] is None:
        state["headless"] = Session(None, name="headless")
    return state["phones"][-1] if state["phones"] else state["headless"]


def _mark_active() -> None:
    act = active_session()
    for s in [state["headless"], *state["phones"]]:
        if s is not None:
            s.active = s is act


async def poll_services() -> None:
    while True:
        state["memory_up"], state["browser_up"] = await asyncio.gather(memory.health(), browser.health())
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    active_session()
    if detector.model is None and not detector.enabled:
        await asyncio.to_thread(detector.load)
    bg = [asyncio.create_task(tts.pregenerate(all_phrases() + FIXED_PHRASES)),
          asyncio.create_task(poll_services()), asyncio.create_task(net.keep_warm(also=llm.keep_warm))]
    if llm.available():
        bg.append(asyncio.create_task(llm.warm_up([config.ROUTER_FALLBACK_MODEL, config.VISION_MODEL, config.SIGNAL_MODEL])))
    yield
    for t in bg:
        t.cancel()


app = FastAPI(title="core", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "phones_connected": len(state["phones"]),
        "active_session": "phone" if state["phones"] else "headless",
        "stt": stt.available(),
        "tts": tts.available(),
        "tts_cached": f"{tts.status['cached']}/{tts.status['total']}",
        "claude": llm.available(),
        "jev": bool(config.TYPESAFE_API_KEY),
        "hazards": detector.enabled,
        "hazard_infer_ms": detector.infer_ms,
        "memory": {"url": config.MEMORY_URL, "up": state["memory_up"]},
        "browser": {"url": config.BROWSER_URL, "up": state["browser_up"]},
        "demo_mode": detector.tracker.demo_mode,
    }


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    session = Session(ws)
    state["phones"].append(session)
    _mark_active()
    await mirror.emit("phone", connected=True)
    log.info("phone connected")
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        state["phones"].remove(session)
        _mark_active()
        await mirror.emit("phone", connected=bool(state["phones"]))
        log.info("phone disconnected")


@app.websocket("/mirror/ws")
async def mirror_ws(ws: WebSocket):
    await mirror.add(ws)
    await ws.send_text(json.dumps({"kind": "phone", "connected": bool(state["phones"])}))
    try:
        while True:
            # The mirror page can type an utterance or push-to-talk through the laptop mic.
            data = json.loads(await ws.receive_text())
            session = active_session()
            if data.get("text"):
                await session.on_message(TextMsg(text=data["text"]))
            elif data.get("ptt") in ("down", "up"):
                await session.on_message(PttMsg(state=data["ptt"]))
            elif data.get("audio"):
                await session.on_message(AudioMsg(ts=0, pcm16_b64=data["audio"], rate=int(data.get("rate", 16000))))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        mirror.remove(ws)


@app.get("/")
@app.get("/mirror")
async def mirror_page():
    return FileResponse(STATIC / "mirror.html")
