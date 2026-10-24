"""Per-turn latency log (JSONL) so PRD latency targets can be measured: logs/turns.jsonl."""
import json
import logging
import time

from . import config

log = logging.getLogger("core.turnlog")


def write(record: dict) -> None:
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "turns.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), **record}) + "\n")
    except Exception as e:
        log.warning("turn log write failed: %s", e)
