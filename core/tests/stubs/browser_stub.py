"""Stand-in for Eng 4's browser service. Run: uvicorn tests.stubs.browser_stub:app --port 8002"""
import uuid

from fastapi import FastAPI

from contracts.browser import ConfirmReq, SayResp, TaskReq, TaskResp, WorkReq

app = FastAPI(title="browser stub")


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
