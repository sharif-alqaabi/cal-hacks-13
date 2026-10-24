"""Shared request log for the stubs: GET /_log returns every request received (jpeg fields dropped)."""
import os
import time

LATENCY_S = float(os.getenv("STUB_LATENCY_MS", "0")) / 1000


def entry(endpoint: str, body: dict) -> dict:
    return {"endpoint": endpoint, "ts": time.time(),
            "body": {k: v for k, v in body.items() if "jpeg" not in k}}
