"""Memory service HTTP contract (owner of the service: Eng 3). Base URL: MEMORY_URL."""
from typing import Literal, Optional

from pydantic import BaseModel


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


class RememberReq(BaseModel):    # POST /remember
    label: str
    ts: float
    jpeg_b64: str


class AlertReq(BaseModel):       # POST /alert
    kind: Literal["lost", "help"]
    note: str = ""


class OkResp(BaseModel):
    ok: bool
