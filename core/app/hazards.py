"""Local hazard loop (C-5): YOLO nano on the laptop, no network on this path.

Warn when a person / bike / car / furniture box is large, centered, low in the frame and growing.
One warning per object class per HAZARD_COOLDOWN_S.
"""
import base64
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from . import config

log = logging.getLogger("core.hazards")

# COCO class name -> spoken name
HAZARD_CLASSES = {
    "person": "person", "bicycle": "bike", "motorcycle": "motorbike", "car": "car",
    "bus": "bus", "truck": "truck", "chair": "chair", "couch": "couch", "bench": "bench",
    "dining table": "table",
}
DIRECTIONS = ["on your left", "slightly left", "ahead", "slightly right", "on your right"]

MIN_AREA = 0.06 if not config.DEMO_MODE else 0.12   # fraction of frame
GROWTH = 1.08                                       # area must grow by 8% vs last sighting
CENTER_BAND = (0.2, 0.8)                            # box center x must be inside this band
MIN_BOTTOM = 1 / 3                                  # box bottom must be in the lower two-thirds


def phrase(name: str, direction: str) -> str:
    return f"Stop, {name} {direction}."


def all_phrases() -> list[str]:
    return [phrase(n, d) for n in sorted(set(HAZARD_CLASSES.values())) for d in DIRECTIONS]


def direction_for(cx: float) -> str:
    if cx < 0.35:
        return DIRECTIONS[0]
    if cx < 0.45:
        return DIRECTIONS[1]
    if cx <= 0.55:
        return DIRECTIONS[2]
    if cx <= 0.65:
        return DIRECTIONS[3]
    return DIRECTIONS[4]


@dataclass
class HazardDetector:
    model: object = None
    last_area: dict[str, float] = field(default_factory=dict)
    last_warned: dict[str, float] = field(default_factory=dict)
    last_run: float = 0.0

    def load(self) -> None:
        if not config.HAZARDS_ENABLED:
            log.info("hazards disabled by env")
            return
        try:
            from ultralytics import YOLO
            self.model = YOLO(config.YOLO_MODEL)
            log.info("YOLO loaded: %s", config.YOLO_MODEL)
        except Exception as e:
            log.warning("YOLO unavailable, hazard loop off: %s", e)

    def due(self) -> bool:
        return self.model is not None and time.time() - self.last_run >= 1 / config.HAZARD_FPS

    def check(self, jpeg_b64: str) -> str | None:
        """Blocking; run in a thread. Returns a warning phrase or None."""
        import cv2

        self.last_run = time.time()
        img = cv2.imdecode(np.frombuffer(base64.b64decode(jpeg_b64), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        result = self.model(img, verbose=False, imgsz=320)[0]
        names = result.names
        best: tuple[float, str, float] | None = None   # (area, spoken name, cx)
        seen: dict[str, float] = {}
        for box in result.boxes:
            cls = names[int(box.cls)]
            if cls not in HAZARD_CLASSES or float(box.conf) < 0.4:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            area = (x2 - x1) * (y2 - y1) / (w * h)
            cx, bottom = (x1 + x2) / 2 / w, y2 / h
            seen[cls] = max(seen.get(cls, 0), area)
            if area < MIN_AREA or not (CENTER_BAND[0] <= cx <= CENTER_BAND[1]) or bottom < MIN_BOTTOM:
                continue
            if cls not in self.last_area or area < self.last_area[cls] * GROWTH:
                continue   # need a previous sighting to know it's growing
            if time.time() - self.last_warned.get(cls, 0) < config.HAZARD_COOLDOWN_S:
                continue
            if best is None or area > best[0]:
                best = (area, cls, cx)
        self.last_area = seen
        if best is None:
            return None
        _, cls, cx = best
        self.last_warned[cls] = time.time()
        return phrase(HAZARD_CLASSES[cls], direction_for(cx))


detector = HazardDetector()
