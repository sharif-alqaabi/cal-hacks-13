"""/stream WebSocket contract between the phone relay (Eng 1) and core.

Every message is JSON with a "type" field. Shapes follow PRD 1.
"""
from typing import Literal, Optional, Union

from pydantic import BaseModel


# ---- phone -> core ----------------------------------------------------------

class FrameMsg(BaseModel):
    type: Literal["frame"] = "frame"
    ts: float                      # unix seconds
    jpeg_b64: str
    w: int
    h: int
    snap_id: Optional[str] = None  # set only when answering a SnapMsg


class AudioMsg(BaseModel):
    type: Literal["audio"] = "audio"
    ts: float
    pcm16_b64: str                 # mono, little-endian 16-bit PCM
    rate: int = 8000


class PttMsg(BaseModel):
    type: Literal["ptt"] = "ptt"
    state: Literal["down", "up"]


class TextMsg(BaseModel):
    """Dev/demo only: skip STT and inject an utterance directly."""
    type: Literal["text"] = "text"
    text: str


InboundMsg = Union[FrameMsg, AudioMsg, PttMsg, TextMsg]


def parse_inbound(raw: str) -> InboundMsg:
    import json
    data = json.loads(raw)
    t = data.get("type")
    model = {"frame": FrameMsg, "audio": AudioMsg, "ptt": PttMsg, "text": TextMsg}.get(t)
    if model is None:
        raise ValueError(f"unknown message type: {t!r}")
    return model.model_validate(data)


# ---- core -> phone ----------------------------------------------------------

class SayMsg(BaseModel):
    type: Literal["say"] = "say"
    id: str
    text: str
    pcm16_b64: str = ""            # empty when TTS is unavailable; phone may fall back to on-device TTS
    rate: int = 24000
    urgent: bool = False           # urgent cuts off whatever is playing


class SnapMsg(BaseModel):
    type: Literal["snap"] = "snap"
    snap_id: str                   # phone answers with one full-res FrameMsg carrying this id


OutboundMsg = Union[SayMsg, SnapMsg]
