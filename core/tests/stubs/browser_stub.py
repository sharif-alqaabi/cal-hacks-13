"""Stand-in for Eng 4's browser service. Run: uvicorn tests.stubs.browser_stub:app --port 8002

Test-only endpoints: GET /_log (requests received), POST /_reset.
"""
import asyncio
import uuid

from fastapi import FastAPI, Request

from contracts.browser import ConfirmReq, SayResp, TaskReq, TaskResp, WorkReq
from tests.stubs._log import LATENCY_S, entry

app = FastAPI(title="browser stub")
state = {"log": []}


@app.middleware("http")
async def record(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/_") and request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        state["log"].append(entry(path, body))
        if LATENCY_S:
            await asyncio.sleep(LATENCY_S)
    return await call_next(request)


@app.get("/_log")
def get_log():
    return state["log"]


@app.post("/_reset")
def reset():
    state["log"].clear()
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "stub": True}


@app.post("/task", response_model=TaskResp)
def task(req: TaskReq):
    return TaskResp(
        task_id=uuid.uuid4().hex[:8],
        say="I drafted an email to Sam: I'm at the Palace of Fine Arts. Should I send it?",
        needs_confirm=True,
    )


@app.post("/confirm", response_model=SayResp)
def confirm(req: ConfirmReq):
    return SayResp(say="Sent." if req.yes else "Okay, I won't send it.")


@app.post("/work", response_model=SayResp)
def work(req: WorkReq):
    return SayResp(say="That's the blue notebook, item one of three. Next, find the stapler.")
