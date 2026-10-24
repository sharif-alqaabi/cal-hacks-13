"""Browser / laptop-agent client (C-9). Point BROWSER_URL at the stub or the real service."""
import httpx

from contracts.browser import ConfirmReq, SayResp, TaskReq, TaskResp, WorkReq
from .. import config

UNAVAILABLE = "The laptop assistant isn't available right now."


def _client(timeout: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=config.BROWSER_URL, timeout=timeout or config.SERVICE_TIMEOUT_S)


async def health() -> bool:
    try:
        async with _client(timeout=1) as c:
            return (await c.get("/health")).status_code < 400
    except Exception:
        return False


async def task(goal: str) -> TaskResp:
    # Drafting can take up to ~30 s on the real agent (PRD 4 B-1).
    async with _client(timeout=40) as c:
        r = await c.post("/task", json=TaskReq(goal=goal).model_dump())
        r.raise_for_status()
        return TaskResp.model_validate(r.json())


async def confirm(task_id: str, yes: bool) -> SayResp:
    async with _client(timeout=40) as c:
        r = await c.post("/confirm", json=ConfirmReq(task_id=task_id, yes=yes).model_dump())
        r.raise_for_status()
        return SayResp.model_validate(r.json())


async def work(utterance: str, jpeg_b64: str) -> SayResp:
    async with _client(timeout=15) as c:
        r = await c.post("/work", json=WorkReq(utterance=utterance, jpeg_b64=jpeg_b64).model_dump())
        r.raise_for_status()
        return SayResp.model_validate(r.json())
