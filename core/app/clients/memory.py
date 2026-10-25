"""Memory service client (C-8). Point MEMORY_URL at the stub or the real service; no code change."""
import httpx

from contracts.memory import AlertReq, IngestReq, OkResp, RecallReq, RecallResp, RememberReq
from .. import config

UNAVAILABLE = "Memory isn't available right now."


def _client(timeout: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=config.MEMORY_URL, timeout=timeout or config.SERVICE_TIMEOUT_S)


async def health() -> bool:
    try:
        async with _client(timeout=1) as c:
            return (await c.get("/health")).status_code < 400
    except Exception:
        return False


async def ingest(ts: float, jpeg_b64: str) -> None:
    async with _client(timeout=config.INGEST_TIMEOUT_S) as c:
        await c.post("/ingest", json=IngestReq(ts=ts, jpeg_b64=jpeg_b64).model_dump())


async def recall(question: str, jpeg_b64: str | None = None) -> RecallResp:
    async with _client() as c:
        r = await c.post("/recall", json=RecallReq(question=question, jpeg_b64=jpeg_b64).model_dump())
        r.raise_for_status()
        return RecallResp.model_validate(r.json())


async def remember(label: str, ts: float, jpeg_b64: str) -> OkResp:
    async with _client() as c:
        r = await c.post("/remember", json=RememberReq(label=label, ts=ts, jpeg_b64=jpeg_b64).model_dump())
        r.raise_for_status()
        return OkResp.model_validate(r.json())


async def alert(kind: str, note: str = "") -> OkResp:
    async with _client() as c:
        r = await c.post("/alert", json=AlertReq(kind=kind, note=note).model_dump())
        r.raise_for_status()
        return OkResp.model_validate(r.json())
