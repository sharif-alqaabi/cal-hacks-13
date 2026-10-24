"""Stand-in for Eng 3's memory service. Run: uvicorn tests.stubs.memory_stub:app --port 8001"""
import time

from fastapi import FastAPI, Response

from contracts.memory import AlertReq, IngestReq, OkResp, RecallReq, RecallResp, RememberReq

app = FastAPI(title="memory stub")
ingested = 0


@app.get("/health")
def health():
    return {"ok": True, "stub": True, "ingested": ingested}


@app.post("/ingest", status_code=202)
def ingest(req: IngestReq):
    global ingested
    ingested += 1
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
