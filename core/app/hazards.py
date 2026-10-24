"""Local hazard loop (C-5): YOLO nano on the laptop, no network on this path.

Warn when a person / bike / car / furniture box is large, in the walking path and growing
(or very close). One warning per object class per HAZARD_COOLDOWN_S.

HazardTracker.decide() is pure so it can be unit tested; HazardDetector wraps the model I/O.
"""
import base64
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger("core.hazards")

# COCO class name -> spoken name
HAZARD_CLASSES = {
    "person": "person", "bicycle": "bike", "motorcycle": "motorbike", "car": "car",
    "bus": "bus", "truck": "truck", "chair": "chair", "couch": "couch", "bench": "bench",
    "dining table": "table",
}
DIRECTIONS = ["on your left", "ahead, slightly left", "ahead", "ahead, slightly right", "on your right"]

MIN_CONF = 0.4
CENTER_BAND = (0.2, 0.8)     # box centre x must be inside this band
MIN_BOTTOM = 1 / 3           # box bottom must be in the lower two-thirds
GROWTH = 1.15                # area vs the largest same-class area seen ~GROWTH_WINDOW_S ago
GROWTH_WINDOW_S = 0.6
VERY_CLOSE = 0.35            # warn even if not growing


@dataclass
class Box:
    cls: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float   # normalised 0..1

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2


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
class HazardTracker:
    demo_mode: bool = field(default_factory=lambda: config.DEMO_MODE)
    cooldown_s: float = field(default_factory=lambda: config.HAZARD_COOLDOWN_S)
    history: dict[str, deque] = field(default_factory=dict)      # cls -> deque[(t, area)]
    last_warned: dict[str, float] = field(default_factory=dict)
    last_box: Box | None = None

    @property
    def min_area(self) -> float:
        return 0.10 if self.demo_mode else 0.06

    def _past_area(self, cls: str, now: float) -> float | None:
        """Largest area seen for cls around GROWTH_WINDOW_S ago (between 0.3 and 1.5 s back)."""
        h = self.history.get(cls)
        if not h:
            return None
        old = [a for t, a in h if GROWTH_WINDOW_S / 2 <= now - t <= GROWTH_WINDOW_S * 2.5]
        return max(old) if old else None

    def decide(self, boxes: list[Box], now: float) -> str | None:
        best: Box | None = None
        seen: dict[str, float] = {}
        for b in boxes:
            if b.cls not in HAZARD_CLASSES or b.conf < MIN_CONF:
                continue
            if self.demo_mode and b.cls == "person":
                continue
            seen[b.cls] = max(seen.get(b.cls, 0.0), b.area)
            in_path = CENTER_BAND[0] <= b.cx <= CENTER_BAND[1] and b.y2 >= MIN_BOTTOM
            if not in_path or b.area < self.min_area:
                continue
            past = self._past_area(b.cls, now)
            growing = past is not None and past > 0 and b.area >= past * GROWTH
            if not (growing or b.area >= VERY_CLOSE):
                continue
            if now - self.last_warned.get(b.cls, -1e9) < self.cooldown_s:
                continue
            if best is None or b.area > best.area:
                best = b
        for cls, area in seen.items():
            h = self.history.setdefault(cls, deque())
            h.append((now, area))
            while h and now - h[0][0] > 2.0:
                h.popleft()
        if best is None:
            return None
        self.last_warned[best.cls] = now
        self.last_box = best
        return phrase(HAZARD_CLASSES[best.cls], direction_for(best.cx))


@dataclass
class HazardDetector:
    model: object = None
    tracker: HazardTracker = field(default_factory=HazardTracker)
    last_run: float = 0.0
    infer_ms: int | None = None
    enabled: bool = False   # True once a detector (real or fake) is ready

    def load(self) -> None:
        if not config.HAZARDS_ENABLED:
            log.info("hazards disabled by env")
            return
        try:
            from ultralytics import YOLO
            path = Path(config.YOLO_MODEL)
            if not path.is_absolute() and (config.ROOT / path).exists():
                path = config.ROOT / path
            self.model = YOLO(str(path))
            dummy = np.zeros((480, 640, 3), np.uint8)
            self.model(dummy, verbose=False, imgsz=config.HAZARD_IMGSZ)   # warm up
            t0 = time.perf_counter()
            self.model(dummy, verbose=False, imgsz=config.HAZARD_IMGSZ)
            self.infer_ms = int((time.perf_counter() - t0) * 1000)
            self.enabled = True
            log.info("YOLO loaded: %s, inference %d ms", path, self.infer_ms)
        except Exception as e:
            log.warning("YOLO unavailable, hazard loop off: %s", e)

    def due(self) -> bool:
        return self.enabled and time.time() - self.last_run >= 1 / config.HAZARD_FPS

    def detect(self, jpeg_b64: str) -> list[Box]:
        """Decode + model. This is the seam tests replace."""
        import cv2

        img = cv2.imdecode(np.frombuffer(base64.b64decode(jpeg_b64), np.uint8), cv2.IMREAD_COLOR)
        if img is None or self.model is None:
            return []
        h, w = img.shape[:2]
        t0 = time.perf_counter()
        result = self.model(img, verbose=False, imgsz=config.HAZARD_IMGSZ)[0]
        self.infer_ms = int((time.perf_counter() - t0) * 1000)
        names = result.names
        out = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            out.append(Box(names[int(box.cls)], float(box.conf), x1 / w, y1 / h, x2 / w, y2 / h))
        return out

    def check(self, jpeg_b64: str, now: float | None = None) -> str | None:
        """Blocking; run in a thread. Returns a warning phrase or None."""
        self.last_run = time.time()
        return self.tracker.decide(self.detect(jpeg_b64), now if now is not None else time.time())


detector = HazardDetector()
