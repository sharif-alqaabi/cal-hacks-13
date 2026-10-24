"""One phone connection on /stream: receives frame/audio/ptt, sends say/snap."""
import asyncio
import base64
import logging
import re
import time
import uuid

from fastapi import WebSocket

from contracts.stream import AudioMsg, FrameMsg, PttMsg, SayMsg, SnapMsg, TextMsg, parse_inbound
from . import config, router, stt, tts, vision
from .clients import browser, memory
from .hazards import detector
from .mirror import mirror
from .safety import filter_reply, max_two_sentences

log = logging.getLogger("core.session")

NO_FRAME = "I can't see anything from the glasses right now."
VISION_DOWN = "I can't look right now, please try again."


class Session:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.send_lock = asyncio.Lock()
        self.latest: FrameMsg | None = None
        self.audio = bytearray()
        self.audio_rate = 8000
        self.ptt_down = False
        self.pending_task_id: str | None = None
        self.snaps: dict[str, asyncio.Future] = {}
        self.hazard_busy = False
        self.tasks: set[asyncio.Task] = set()

    # ---- plumbing -----------------------------------------------------------

    def spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    async def send(self, msg) -> None:
        async with self.send_lock:
            await self.ws.send_text(msg.model_dump_json())

    async def say(self, text: str, urgent: bool = False) -> None:
        text = filter_reply(max_two_sentences(text))
        t0 = time.perf_counter()
        audio = await tts.synth(text)
        tts_ms = int((time.perf_counter() - t0) * 1000)
        await self.send(SayMsg(id=uuid.uuid4().hex[:8], text=text, pcm16_b64=audio, rate=config.TTS_RATE, urgent=urgent))
        await mirror.emit("say", text=text, urgent=urgent, pcm16_b64=audio, rate=config.TTS_RATE, tts_ms=tts_ms)

    async def run(self) -> None:
        self.spawn(self.ingest_loop())
        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    msg = parse_inbound(raw)
                except Exception as e:
                    log.warning("bad message: %s", e)
                    continue
                await self.on_message(msg)
        finally:
            for t in list(self.tasks):
                t.cancel()

    async def on_message(self, msg) -> None:
        if isinstance(msg, FrameMsg):
            self.on_frame(msg)
        elif isinstance(msg, AudioMsg):
            self.audio_rate = msg.rate
            if self.ptt_down:
                self.audio.extend(base64.b64decode(msg.pcm16_b64))
            # TODO(C-2): when streaming STT lands, forward audio continuously and use turn detection.
        elif isinstance(msg, PttMsg):
            await mirror.emit("ptt", state=msg.state)
            if msg.state == "down":
                self.ptt_down = True
                self.audio.clear()
            else:
                self.ptt_down = False
                pcm = bytes(self.audio)
                self.audio.clear()
                self.spawn(self.on_speech(pcm, self.audio_rate))
        elif isinstance(msg, TextMsg):
            self.spawn(self.handle_utterance(msg.text))

    # ---- frames & hazards ---------------------------------------------------

    def on_frame(self, f: FrameMsg) -> None:
        if f.snap_id and f.snap_id in self.snaps:
            fut = self.snaps.pop(f.snap_id)
            if not fut.done():
                fut.set_result(f)
        self.latest = f
        if detector.due() and not self.hazard_busy:
            self.hazard_busy = True
            self.spawn(self.check_hazard(f))

    async def check_hazard(self, f: FrameMsg) -> None:
        try:
            warning = await asyncio.to_thread(detector.check, f.jpeg_b64)
            if warning:
                lag_ms = int((time.time() - f.ts) * 1000)
                await mirror.emit("hazard", text=warning, lag_ms=lag_ms)
                await self.say(warning, urgent=True)   # audio is pre-generated, no network
        except Exception as e:
            log.error("hazard check failed: %s", e)
        finally:
            self.hazard_busy = False

    async def fresh_frame(self, timeout: float = 1.2) -> FrameMsg | None:
        """Ask the phone for a full-res frame; fall back to the latest streamed one."""
        snap_id = uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        self.snaps[snap_id] = fut
        try:
            await self.send(SnapMsg(snap_id=snap_id))
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.snaps.pop(snap_id, None)
            return self.latest

    async def ingest_loop(self) -> None:
        # TODO(C-8): also ingest on scene change, not just on a timer.
        last_ts = 0.0
        while True:
            await asyncio.sleep(config.INGEST_EVERY_S)
            f = self.latest
            if f is None or f.ts == last_ts:
                continue
            last_ts = f.ts
            try:
                await memory.ingest(f.ts, f.jpeg_b64)
            except Exception as e:
                log.debug("ingest failed: %s", e)

    # ---- voice loop ---------------------------------------------------------

    async def on_speech(self, pcm: bytes, rate: int) -> None:
        t0 = time.perf_counter()
        try:
            text = await stt.transcribe(pcm, rate)
        except Exception as e:
            log.error("STT failed: %s", e)
            await self.say("Sorry, I couldn't hear that.")
            return
        await mirror.emit("stt", ms=int((time.perf_counter() - t0) * 1000))
        if text:
            await self.handle_utterance(text)

    async def handle_utterance(self, text: str) -> None:
        await mirror.emit("transcript", text=text)
        t0 = time.perf_counter()
        intent, source = await router.route(text, pending_confirm=self.pending_task_id is not None)
        route_ms = int((time.perf_counter() - t0) * 1000)
        await mirror.emit("intent", intent=intent, source=source, ms=route_ms)

        t1 = time.perf_counter()
        reply = await self.dispatch(intent, text)
        await mirror.emit("handled", intent=intent, ms=int((time.perf_counter() - t1) * 1000))
        if reply:
            await self.say(reply)

    async def dispatch(self, intent: str, text: str) -> str:
        handler = getattr(self, f"do_{intent}", self.do_other)
        return await handler(text)

    async def do_describe(self, text: str) -> str:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        try:
            return await vision.describe(f.jpeg_b64)
        except Exception as e:
            log.error("describe failed: %s", e)
            return VISION_DOWN

    async def do_signal(self, text: str) -> str:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        try:
            return await vision.signal(f.jpeg_b64)
        except Exception as e:
            log.error("signal failed: %s", e)
            return VISION_DOWN

    async def do_recall(self, text: str) -> str:
        try:
            return (await memory.recall(text)).answer
        except Exception as e:
            log.error("recall failed: %s", e)
            return memory.UNAVAILABLE

    async def do_remember(self, text: str) -> str:
        f = self.latest
        if f is None:
            return NO_FRAME
        try:
            await memory.remember(text, f.ts, f.jpeg_b64)
            return "Got it, I'll remember that."
        except Exception as e:
            log.error("remember failed: %s", e)
            return memory.UNAVAILABLE

    async def do_lost(self, text: str) -> str:
        kind = "help" if re.search(r"\bhelp\b", text, re.I) and "lost" not in text.lower() else "lost"
        try:
            await memory.alert(kind, note=text)
            return "I've let your family know where you are."
        except Exception as e:
            log.error("alert failed: %s", e)
            return "I couldn't reach your family right now."

    async def do_browser(self, text: str) -> str:
        await self.say("Working on it.")
        try:
            r = await browser.task(text)
        except Exception as e:
            log.error("browser task failed: %s", e)
            return browser.UNAVAILABLE
        self.pending_task_id = r.task_id if r.needs_confirm else None
        return r.say

    async def do_confirm(self, text: str) -> str:
        if not self.pending_task_id:
            return "There's nothing waiting for a yes right now."
        yes = not re.search(r"\b(no|nope|cancel|don't|stop)\b", text, re.I)
        task_id, self.pending_task_id = self.pending_task_id, None
        try:
            return (await browser.confirm(task_id, yes)).say
        except Exception as e:
            log.error("confirm failed: %s", e)
            return browser.UNAVAILABLE

    async def do_task(self, text: str) -> str:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        try:
            return (await browser.work(text, f.jpeg_b64)).say
        except Exception as e:
            log.error("work failed: %s", e)
            return browser.UNAVAILABLE

    async def do_other(self, text: str) -> str:
        try:
            return await vision.chat(text)
        except Exception:
            return "Sorry, I didn't catch what you need."
