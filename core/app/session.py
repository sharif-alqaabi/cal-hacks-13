"""One wearer session: receives frame/audio/ptt/text, sends say/snap.

A session with ws=None is "headless": nothing is sent to a phone, but mirror events and laptop
audio still happen, so the whole voice loop can run from the mirror page alone.
"""
import asyncio
import base64
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Union

import numpy as np

from contracts.stream import AudioMsg, FrameMsg, PttMsg, SayMsg, SnapMsg, TextMsg, parse_inbound
from . import config, router, stt, tts, turnlog, vision
from .clients import browser, memory
from .hazards import detector
from .mirror import mirror
from .safety import FALLBACK, filter_sentence, split_sentences

log = logging.getLogger("core.session")

NO_FRAME = "I can't see anything from the glasses right now."
VISION_DOWN = "I can't look right now, please try again."
NOT_HEARD = "Sorry, I couldn't hear that."
NOT_CAUGHT = "Sorry, I didn't catch what you need."
WORKING = "Working on it."
REMEMBERED = "Got it, I'll remember that."
NOT_REMEMBERED = "Sorry, I didn't catch what to remember."
FAMILY_TOLD = "I've let your family know where you are."
FAMILY_DOWN = "I couldn't reach your family right now."
NOTHING_PENDING = "There's nothing waiting for a yes right now."
HAZARDS_OFF = "Obstacle warnings are off."

FIXED_PHRASES = [WORKING, REMEMBERED, NOT_REMEMBERED, FAMILY_TOLD, FAMILY_DOWN, memory.UNAVAILABLE, browser.UNAVAILABLE,
                 NO_FRAME, VISION_DOWN, FALLBACK, NOT_HEARD, NOT_CAUGHT, NOTHING_PENDING, HAZARDS_OFF,
                 *vision.SIGNAL_SENTENCES.values()]



class Verbatim(str):
    """A reply spoken as one say, not split or capped (browser draft read-backs end in the question)."""


Reply = Union[str, list, AsyncIterator[str], None]


@dataclass
class Turn:
    t0: float = field(default_factory=time.perf_counter)   # PTT up or text arrival
    transcript: str = ""
    intent: str = ""
    route_source: str = ""
    stt_ms: int | None = None
    route_ms: int | None = None
    handler_ms: int | None = None
    first_audio_ms: int | None = None
    reply: list[str] = field(default_factory=list)
    banned_blocked: int = 0
    t_handler: float = 0.0   # perf_counter when the handler started

    def ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def thumb(jpeg_b64: str) -> np.ndarray | None:
    import cv2

    img = cv2.imdecode(np.frombuffer(base64.b64decode(jpeg_b64), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if img is None:
        return None
    return cv2.resize(img, (16, 12), interpolation=cv2.INTER_AREA).astype(np.float32)


class Session:
    def __init__(self, ws=None, name: str = "phone") -> None:
        self.ws = ws
        self.name = name
        self.active = ws is None
        self.send_lock = asyncio.Lock()
        self.latest: FrameMsg | None = None
        self.pending_task_id: str | None = None
        self.snaps: dict[str, asyncio.Future] = {}
        self.hazard_busy = False
        self.tasks: set[asyncio.Task] = set()
        self.turn_task: asyncio.Task | None = None
        # push-to-talk state
        self.ptt_open = False
        self.audio_q: asyncio.Queue | None = None
        self.stt_task: asyncio.Task | None = None
        # ingest / mirror frame state
        self.last_ingest = 0.0
        self.last_thumb: np.ndarray | None = None
        self.last_mirror_frame = 0.0

    # ---- plumbing -----------------------------------------------------------

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    async def send(self, msg) -> None:
        if self.ws is None:
            return
        async with self.send_lock:
            await self.ws.send_text(msg.model_dump_json())

    async def say(self, text: str, urgent: bool = False, turn: Turn | None = None) -> None:
        """Send one already-filtered line. Synthesis happens outside send_lock so hazards never queue behind it."""
        t0 = time.perf_counter()
        audio = await (tts.synth_urgent(text) if urgent else tts.synth(text))
        tts_ms = int((time.perf_counter() - t0) * 1000)
        await self.send(SayMsg(id=uuid.uuid4().hex[:8], text=text, pcm16_b64=audio, rate=config.TTS_RATE, urgent=urgent))
        if turn is not None and turn.first_audio_ms is None:
            turn.first_audio_ms = turn.ms()
        await mirror.emit("say", text=text, urgent=urgent, pcm16_b64=audio, rate=config.TTS_RATE, tts_ms=tts_ms)

    async def speak(self, reply: Reply, turn: Turn) -> None:
        """Cap at two sentences, filter each, synthesise and send one say per sentence as it arrives."""
        spoken: list[str] = []
        t_start = turn.t_handler or time.perf_counter()
        chunks = _aiter(reply)
        try:
            async for chunk in chunks:
                for s in ([chunk] if isinstance(chunk, Verbatim) else split_sentences(chunk)):
                    if len(spoken) >= 2:
                        break
                    if turn.handler_ms is None:
                        turn.handler_ms = int((time.perf_counter() - t_start) * 1000)
                    kept = filter_sentence(s)
                    if kept is None:
                        turn.banned_blocked += 1
                        continue
                    spoken.append(kept)
                    if config.SAY_SPLIT:
                        await self.say(kept, turn=turn)
                if len(spoken) >= 2:
                    break
        finally:
            await chunks.aclose()
        if not spoken and turn.banned_blocked:
            spoken.append(FALLBACK)
            if config.SAY_SPLIT:
                await self.say(FALLBACK, turn=turn)
        if spoken and not config.SAY_SPLIT:
            await self.say(" ".join(spoken), turn=turn)
        turn.reply.extend(spoken)

    async def run(self) -> None:
        if not detector.enabled:
            self.spawn(self.say(HAZARDS_OFF))
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
            self.close()

    def close(self) -> None:
        for t in list(self.tasks):
            t.cancel()

    async def on_message(self, msg) -> None:
        if isinstance(msg, FrameMsg):
            self.on_frame(msg)
        elif isinstance(msg, AudioMsg):
            self.on_audio(base64.b64decode(msg.pcm16_b64), msg.rate)
        elif isinstance(msg, PttMsg):
            await mirror.emit("ptt", state=msg.state)
            if msg.state == "down":
                self.ptt_down()
            else:
                self.ptt_up()
        elif isinstance(msg, TextMsg):
            self.start_turn(self.handle_utterance(msg.text, Turn()))

    def start_turn(self, coro) -> None:
        """Barge-in: a new turn cancels the in-flight one. Hazard warnings are separate tasks and never cancelled."""
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = self.spawn(coro)

    # ---- push-to-talk -------------------------------------------------------

    def ptt_down(self) -> None:
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        if self.stt_task and not self.stt_task.done():
            self.stt_task.cancel()
        self.ptt_open = True
        self.audio_q = None
        self.stt_task = None

    def on_audio(self, pcm: bytes, rate: int) -> None:
        if not self.ptt_open:
            return
        if self.audio_q is None:
            # Open the STT stream lazily on the first chunk so we know the rate and setup overlaps speech.
            self.audio_q = asyncio.Queue()
            self.stt_task = self.spawn(self.stt_pump(rate, self.audio_q))
        self.audio_q.put_nowait(pcm)

    async def stt_pump(self, rate: int, q: asyncio.Queue) -> str:
        """Feeds queued audio into one STT turn; a None item means PTT up. Returns the transcript."""
        try:
            turn = await stt.start_turn(rate)
        except Exception as e:
            log.error("STT start failed: %s", e)
            while await q.get() is not None:   # drain until PTT up
                pass
            raise
        try:
            while (pcm := await q.get()) is not None:
                await turn.feed(pcm)
            return await turn.finish()
        except asyncio.CancelledError:
            await turn.cancel()
            raise

    def ptt_up(self) -> None:
        if not self.ptt_open:
            return
        self.ptt_open = False
        if self.audio_q is None:
            return   # no audio arrived: an accidental tap
        self.audio_q.put_nowait(None)
        self.start_turn(self.finish_turn(self.stt_task, Turn()))

    async def finish_turn(self, stt_task: asyncio.Task, turn: Turn) -> None:
        try:
            text = await asyncio.wait_for(asyncio.shield(stt_task), config.STT_FINISH_TIMEOUT_S + 1)
        except asyncio.CancelledError:
            stt_task.cancel()
            raise
        except Exception as e:
            log.error("STT failed: %s", e)
            text = ""
        turn.stt_ms = turn.ms()
        await mirror.emit("stt", ms=turn.stt_ms)
        if not text:
            turn.reply.append(NOT_HEARD)
            await self.say(NOT_HEARD, turn=turn)
            self.log_turn(turn)
            return
        await self.handle_utterance(text, turn)

    # ---- frames, hazards, ingest --------------------------------------------

    def on_frame(self, f: FrameMsg) -> None:
        if f.snap_id:
            fut = self.snaps.pop(f.snap_id, None)
            if fut and not fut.done():
                fut.set_result(f)
            self.latest = f
            return   # snap frames are large duplicates: no hazard check, no ingest
        self.latest = f
        if detector.due() and not self.hazard_busy:
            self.hazard_busy = True
            self.spawn(self.check_hazard(f))
        self.maybe_ingest(f)
        now = time.time()
        if self.active and mirror.clients and now - self.last_mirror_frame >= 1 / config.MIRROR_FRAME_FPS:
            self.last_mirror_frame = now
            self.spawn(mirror.emit("frame", jpeg_b64=f.jpeg_b64))

    def maybe_ingest(self, f: FrameMsg) -> None:
        now = time.time()
        since = now - self.last_ingest
        if since < 1.0:
            return
        try:
            th = thumb(f.jpeg_b64)
        except Exception:
            th = None
        changed = (th is not None and self.last_thumb is not None
                   and float(np.abs(th - self.last_thumb).mean()) > config.SCENE_CHANGE_THRESHOLD)
        if since >= config.INGEST_EVERY_S or changed:
            self.last_ingest = now
            if th is not None:
                self.last_thumb = th
            self.spawn(self.ingest(f))

    async def ingest(self, f: FrameMsg) -> None:
        try:
            await memory.ingest(f.ts, f.jpeg_b64)
        except Exception as e:
            log.debug("ingest failed: %s", e)

    async def check_hazard(self, f: FrameMsg) -> None:
        try:
            warning = await asyncio.to_thread(detector.check, f.jpeg_b64)
            if warning:
                lag_ms = int((time.time() - f.ts) * 1000)
                b = detector.tracker.last_box
                box = [b.x1, b.y1, b.x2, b.y2] if b else None
                await mirror.emit("hazard", text=warning, lag_ms=lag_ms, box=box)
                await self.say(warning, urgent=True)   # audio comes from the pre-generated cache
                turnlog.write({"kind": "hazard", "text": warning, "lag_ms": lag_ms})
        except Exception as e:
            log.error("hazard check failed: %s", e)
        finally:
            self.hazard_busy = False

    async def fresh_frame(self, timeout: float = 1.2) -> FrameMsg | None:
        """Ask the phone for a full-res frame; fall back to the latest streamed one."""
        if self.ws is None:
            return self.latest
        snap_id = uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        self.snaps[snap_id] = fut
        try:
            await self.send(SnapMsg(snap_id=snap_id))
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, Exception):
            self.snaps.pop(snap_id, None)
            return self.latest

    # ---- voice loop ---------------------------------------------------------

    async def handle_utterance(self, text: str, turn: Turn) -> None:
        turn.transcript = text
        await mirror.emit("transcript", text=text)
        try:
            intent, source, route_ms = await router.route(text, pending_confirm=self.pending_task_id is not None)
            turn.intent, turn.route_source, turn.route_ms = intent, source, route_ms
            await mirror.emit("intent", intent=intent, source=source, ms=route_ms)
            handler = getattr(self, f"do_{intent}", self.do_other)
            t1 = turn.t_handler = time.perf_counter()
            await self.speak(await handler(text, turn), turn)
            await mirror.emit("handled", intent=intent, ms=int((time.perf_counter() - t1) * 1000))
        finally:
            self.log_turn(turn)

    def log_turn(self, turn: Turn) -> None:
        rec = {"transcript": turn.transcript, "intent": turn.intent, "route_source": turn.route_source,
               "stt_ms": turn.stt_ms, "route_ms": turn.route_ms, "handler_ms": turn.handler_ms,
               "first_audio_ms": turn.first_audio_ms, "total_ms": turn.ms(), "reply": " ".join(turn.reply),
               "banned_blocked": turn.banned_blocked}
        turnlog.write(rec)
        self.spawn(mirror.emit("turn", **rec))

    async def do_describe(self, text: str, turn: Turn) -> Reply:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        return self._describe_stream(f.jpeg_b64)

    async def _describe_stream(self, jpeg_b64: str) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.VISION_TIMEOUT_S
        it = vision.describe(jpeg_b64).__aiter__()
        got = False
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                s = await asyncio.wait_for(it.__anext__(), remaining)
                got = True
                yield s
        except StopAsyncIteration:
            pass
        except Exception as e:
            log.error("describe failed: %r", e)
            if not got:
                yield VISION_DOWN
        finally:
            try:
                await it.aclose()
            except Exception:
                pass

    async def do_signal(self, text: str, turn: Turn) -> Reply:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        try:
            return await asyncio.wait_for(vision.signal(f.jpeg_b64), config.VISION_TIMEOUT_S)
        except Exception as e:
            log.error("signal failed: %r", e)
            return VISION_DOWN

    async def do_recall(self, text: str, turn: Turn) -> Reply:
        try:
            r = await memory.recall(text)
        except Exception as e:
            log.error("recall failed: %r", e)
            return memory.UNAVAILABLE
        if r.thumb_url:
            await mirror.emit("recall", answer=r.answer, thumb_url=r.thumb_url, ts=r.ts)
        return r.answer

    async def do_remember(self, text: str, turn: Turn) -> Reply:
        f = self.latest
        if f is None:
            return NO_FRAME
        try:
            r = await memory.remember(text, f.ts, f.jpeg_b64)
            return REMEMBERED if r.ok else NOT_REMEMBERED   # memory says ok=false when it found no name or fact
        except Exception as e:
            log.error("remember failed: %r", e)
            return memory.UNAVAILABLE

    async def do_lost(self, text: str, turn: Turn) -> Reply:
        kind = "help" if re.search(r"\bhelp\b", text, re.I) and "lost" not in text.lower() else "lost"
        try:
            await memory.alert(kind, note=text)
            return FAMILY_TOLD
        except Exception as e:
            log.error("alert failed: %r", e)
            return FAMILY_DOWN

    async def do_browser(self, text: str, turn: Turn) -> Reply:
        await self.say(WORKING, turn=turn)
        turn.reply.append(WORKING)
        try:
            r = await browser.task(text)
        except Exception as e:
            log.error("browser task failed: %r", e)
            return browser.UNAVAILABLE
        self.pending_task_id = r.task_id if r.needs_confirm else None
        return Verbatim(r.say)

    async def do_confirm(self, text: str, turn: Turn) -> Reply:
        if not self.pending_task_id:
            return NOTHING_PENDING
        yes = not re.search(r"\b(no|nope|cancel|don't|stop)\b", text, re.I)
        task_id, self.pending_task_id = self.pending_task_id, None
        try:
            return (await browser.confirm(task_id, yes)).say
        except Exception as e:
            log.error("confirm failed: %r", e)
            return browser.UNAVAILABLE

    async def do_task(self, text: str, turn: Turn) -> Reply:
        f = await self.fresh_frame()
        if f is None:
            return NO_FRAME
        try:
            return (await browser.work(text, f.jpeg_b64)).say
        except Exception as e:
            log.error("work failed: %r", e)
            return browser.UNAVAILABLE

    async def do_other(self, text: str, turn: Turn) -> Reply:
        try:
            return await asyncio.wait_for(vision.chat(text), config.CHAT_TIMEOUT_S)
        except Exception:
            return NOT_CAUGHT


async def _aiter(reply: Reply) -> AsyncIterator[str]:
    if reply is None:
        return
    if isinstance(reply, str):
        yield reply
    elif isinstance(reply, (list, tuple)):
        for r in reply:
            yield r
    else:
        try:
            async for r in reply:
                yield r
        finally:
            if hasattr(reply, "aclose"):
                await reply.aclose()
