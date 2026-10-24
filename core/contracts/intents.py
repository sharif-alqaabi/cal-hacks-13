"""Intent labels the router chooses between (owner: core)."""
from typing import Literal

Intent = Literal[
    "describe",  # "what's in front of me?"
    "signal",    # "what does the signal say?"
    "recall",    # "where did I put my keys?"
    "remember",  # "this is my brother Sam"
    "lost",      # "I'm lost" / "help"
    "browser",   # "email Sam that I'm at the Palace of Fine Arts"
    "confirm",   # "yes, send it" / "no, cancel"
    "task",      # work mode: "is this the right item?"
    "other",
]

INTENTS: list[str] = list(Intent.__args__)  # type: ignore[attr-defined]
