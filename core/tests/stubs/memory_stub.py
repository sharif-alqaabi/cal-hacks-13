"""Stand-in for Eng 3's memory service. Run: uvicorn tests.stubs.memory_stub:app --port 8001

Test-only endpoints: GET /_log (requests received), POST /_fail {"on": true} (everything returns 503),
POST /_reset (clear the log).
"""
import asyncio
import time

from fastapi import FastAPI, HTTPException, Request, Response

from contracts.memory import AlertReq, IngestReq, OkResp, RecallReq, RecallResp, RememberReq
from tests.stubs._log import LATENCY_S, entry

app = FastAPI(title="memory stub")
state = {"fail": False, "log": []}


@app.middleware("http")
async def record(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/_"):
        body = {}
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                pass
        state["log"].append(entry(path, body))
        if state["fail"]:
            return Response(status_code=503)
        if LATENCY_S:
            await asyncio.sleep(LATENCY_S)
    return await call_next(request)


@app.get("/_log")
def get_log():
    return state["log"]


@app.post("/_fail")
def set_fail(body: dict):
    state["fail"] = bool(body.get("on"))
    return {"fail": state["fail"]}


@app.post("/_reset")
def reset():
    state["log"].clear()
    state["fail"] = False
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "stub": True, "ingested": sum(e["endpoint"] == "/ingest" for e in state["log"])}


@app.post("/ingest", status_code=202)
def ingest(req: IngestReq):
    return Response(status_code=202)


@app.post("/recall", response_model=RecallResp)
def recall(req: RecallReq):
    return RecallResp(answer="Your keys are on the table, 3:42 PM.", ts=time.time(), thumb_url=None)


@app.post("/remember", response_model=OkResp)
def remember(req: RememberReq):
    print(f"[memory stub] remember: {req.label!r}")
    return OkResp(ok=True)


@app.post("/alert", response_model=OkResp)
def alert(req: AlertReq):
    print(f"[memory stub] ALERT {req.kind}: {req.note!r}")
    return OkResp(ok=True)
