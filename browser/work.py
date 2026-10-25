"""Work mode (PRD 4 B-8, P2): hold up an item, hear whether it belongs to the order and what to pick next.

One Claude Sonnet vision call compares the frame with the order card; progress is kept here, per order.
"""
import json
import logging
import re

import config
import llm

log = logging.getLogger("browser.work")

ORDER_PATH = config.HERE / "orders" / "order12.json"
RESET_RX = re.compile(r"\b(start over|reset|new order|from the top)\b", re.I)

SYSTEM = """You help a blind warehouse worker check items against an order card. Look only at the item the person is
holding up or pointing the camera at. Reply with JSON only:
{"item_index": <1-based index of the matching order item, or null>, "what_i_see": "<3 to 6 words naming the item>"}
Match only when the item clearly fits the order item's description."""

_order: dict | None = None
_picked: set[int] = set()


def order() -> dict:
    global _order
    if _order is None:
        _order = json.loads(ORDER_PATH.read_text())
    return _order


def reset() -> None:
    _picked.clear()


def _next_item() -> str | None:
    for i, item in enumerate(order()["items"], 1):
        if i not in _picked:
            return item["name"]
    return None


def reply_for(index: int | None, seen: str) -> str:
    items, oid = order()["items"], order()["order_id"]
    n = len(items)
    if index is None or not 1 <= index <= n:
        nxt = _next_item()
        tail = f" You still need the {nxt}." if nxt else ""
        return f"That looks like {seen or 'something else'}, which isn't on order {oid}.{tail}"
    name = items[index - 1]["name"]
    if index in _picked:
        nxt = _next_item()
        return f"You already have the {name}." + (f" Next, find the {nxt}." if nxt else f" Order {oid} is complete.")
    _picked.add(index)
    nxt = _next_item()
    if nxt is None:
        return f"That's the {name}. That's all {n} items for order {oid}."
    return f"That's the {name}, item {index} of {n}. Next, find the {nxt}."


async def check(utterance: str, jpeg_b64: str) -> str:
    if RESET_RX.search(utterance):
        reset()
        return f"Starting order {order()['order_id']} again. First, find the {_next_item()}."
    if not llm.available():
        return "Work mode needs the Claude key."
    card = "\n".join(f"{i}. {it['name']}: {it['description']}" for i, it in enumerate(order()["items"], 1))
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}},
        {"type": "text", "text": f"Order {order()['order_id']}:\n{card}\n\nThe worker said: \"{utterance}\""},
    ]
    j = await llm.ask_json(SYSTEM, content, max_tokens=120, timeout=10.0, model=config.WORK_MODEL)
    if j is None:
        return "I couldn't check that item. Please try again."
    idx = j.get("item_index")
    return reply_for(int(idx) if isinstance(idx, (int, float)) else None, str(j.get("what_i_see", "")).strip())
