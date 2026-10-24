"""Step-by-step trace of what the agent did, for the judges' screen (GET /trace)."""
import threading
import time
from collections import deque

_events: deque = deque(maxlen=400)
_lock = threading.Lock()
_seq = 0


def emit(task_id: str, kind: str, text: str, **data) -> None:
    """kind: goal, plan, predict, act, guard, draft, readback, confirm, verify, answer, fail."""
    global _seq
    with _lock:
        _seq += 1
        _events.append({"seq": _seq, "ts": time.time(), "task_id": task_id, "kind": kind, "text": text, **data})


def since(seq: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _events if e["seq"] > seq]


def clear() -> None:
    with _lock:
        _events.clear()
