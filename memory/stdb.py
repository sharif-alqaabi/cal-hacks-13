"""SpacetimeDB over HTTP. There is no Python SDK, so reducers are POSTs and reads are SQL on public tables."""
import os

import httpx

HOST = os.environ.get("SPACETIME_HOST", "https://maincloud.spacetimedb.com")


class Stdb:
    def __init__(self):
        self.http = httpx.AsyncClient(
            base_url=f"{HOST}/v1/database/{os.environ['SPACETIME_DB']}",
            headers={"Authorization": f"Bearer {os.environ['SPACETIME_TOKEN']}"},
            timeout=10,
            # Measured: the default 5 s keepalive reconnects (a TLS handshake, ~250 ms) after any quiet moment.
            limits=httpx.Limits(keepalive_expiry=120),
        )

    async def call(self, reducer: str, *args) -> None:
        """Call a reducer; args are positional, in the order the module declares them."""
        r = await self.http.post(f"/call/{reducer}", json=list(args))
        if r.is_error:
            raise RuntimeError(f"{reducer}: HTTP {r.status_code} {r.text}")

    async def sql(self, query: str) -> list[dict]:
        """Run one SELECT and return its rows as dicts keyed by column name."""
        r = await self.http.post("/sql", content=query)
        if r.is_error:
            raise RuntimeError(f"sql: HTTP {r.status_code} {r.text}")
        out = r.json()[0]
        cols = [e["name"]["some"] for e in out["schema"]["elements"]]
        return [dict(zip(cols, row)) for row in out["rows"]]

    async def close(self) -> None:
        await self.http.aclose()
