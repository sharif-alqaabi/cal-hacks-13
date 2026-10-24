"""Browser / laptop-agent HTTP contract (owner of the service: Eng 4). Base URL: BROWSER_URL."""
from pydantic import BaseModel


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
