"""Local hazard loop (C-5): YOLO nano on the laptop, no network on this path.

Warn when a person / bike / car / furniture box is large, in the walking path and growing
(or very close). YOLO's ByteTrack gives each object an id; each tracked object is warned about once,
and again only if it is closing in fast. Boxes without an id fall back to one warning per class per
HAZARD_COOLDOWN_S.

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
FAST_GROWTH = 1.35           # "closing in fast" (and very close): breaks through the cooldown
REWARN_GROWTH = 1.5          # ...and must also be this much bigger than when we last warned
REWARN_MIN_GAP_S = 3.0       # never repeat an object faster than this
INHERIT_IOU = 0.4            # a new track id overlapping a just-lost one is the same object (id switch)
INHERIT_S = 3.0
FORGET_S = 30.0              # drop tracks not seen for this long


@dataclass
class Box:
    cls: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float   # normalised 0..1
    tid: int | None = None   # ByteTrack id, None when tracking is unavailable

    @property
    def key(self) -> str:
        return self.cls if self.tid is None else f"{self.cls}#{self.tid}"

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2


def iou(a: Box, b: Box) -> float:
    w = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    h = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = w * h
    return inter / (a.area + b.area - inter) if inter else 0.0


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
    cooldown_s: float = field(default_factory=lambda: config.HAZARD_COOLDOWN_S)   # untracked boxes only
    history: dict[str, deque] = field(default_factory=dict)      # key -> deque[(t, area)]
    last_warned: dict[str, tuple[float, float]] = field(default_factory=dict)   # key -> (t, area)
    last_seen: dict[str, tuple[float, Box]] = field(default_factory=dict)       # key -> (t, box)
    last_box: Box | None = None

    @property
    def min_area(self) -> float:
        return 0.10 if self.demo_mode else 0.06

    def _past_area(self, key: str, now: float) -> float | None:
        """Largest area seen for key around GROWTH_WINDOW_S ago (between 0.3 and 1.5 s back)."""
        h = self.history.get(key)
        if not h:
            return None
        old = [a for t, a in h if GROWTH_WINDOW_S / 2 <= now - t <= GROWTH_WINDOW_S * 2.5]
        return max(old) if old else None

    def _inherit(self, b: Box, now: float) -> None:
        """A box sitting where a same-class object just was is that object (an id switch, or a box flickering
        between tracked and untracked): it takes over that object's growth history and any warning."""
        new, unwarned = b.key not in self.last_seen, b.key not in self.last_warned
        if not (new or unwarned):
            return
        for k, (t, old) in self.last_seen.items():
            if k == b.key or old.cls != b.cls or now - t > INHERIT_S or iou(old, b) < INHERIT_IOU:
                continue
            if new:
                self.history[b.key] = deque(self.history.get(k, ()))
            if unwarned and k in self.last_warned:
                self.last_warned[b.key] = self.last_warned[k]
            return

    def decide(self, boxes: list[Box], now: float) -> str | None:
        best: Box | None = None
        seen: dict[str, Box] = {}
        for b in boxes:
            if b.cls not in HAZARD_CLASSES or b.conf < MIN_CONF:
                continue
            if self.demo_mode and b.cls == "person":
                continue
            self._inherit(b, now)
            if b.key not in seen or b.area > seen[b.key].area:
                seen[b.key] = b
            in_path = CENTER_BAND[0] <= b.cx <= CENTER_BAND[1] and b.y2 >= MIN_BOTTOM
            if not in_path or b.area < self.min_area:
                continue
            past = self._past_area(b.key, now)
            growing = past is not None and past > 0 and b.area >= past * GROWTH
            if not (growing or b.area >= VERY_CLOSE):
                continue
            if b.key in self.last_warned:
                t_warn, a_warn = self.last_warned[b.key]
                fast = past is not None and past > 0 and b.area >= past * FAST_GROWTH
                closing = (fast and b.area >= max(VERY_CLOSE, a_warn * REWARN_GROWTH)
                           and now - t_warn >= REWARN_MIN_GAP_S)
                expired = b.tid is None and now - t_warn >= self.cooldown_s
                if not (closing or expired):
                    continue
            if best is None or b.area > best.area:
                best = b
        for key, b in seen.items():
            self.last_seen[key] = (now, b)
            h = self.history.setdefault(key, deque())
            h.append((now, b.area))
            while h and now - h[0][0] > 2.0:
                h.popleft()
        for key in [k for k, (t, _) in self.last_seen.items() if now - t > FORGET_S]:
            self.last_seen.pop(key)
            self.history.pop(key, None)
            self.last_warned.pop(key, None)
        if best is None:
            return None
        self.last_warned[best.key] = (now, best.area)
        self.last_box = best
        return phrase(HAZARD_CLASSES[best.cls], direction_for(best.cx))


@dataclass
class HazardDetector:
    model: object = None
    bytetrack: object = None   # ultralytics BYTETracker, fed raw detections so box sizes aren't Kalman-smoothed
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
            try:
                from ultralytics.trackers.byte_tracker import BYTETracker
                from ultralytics.utils import IterableSimpleNamespace, YAML
                from ultralytics.utils.checks import check_yaml
                cfg = IterableSimpleNamespace(**YAML.load(check_yaml("bytetrack.yaml")))
                cfg.track_buffer = round(6 * config.HAZARD_FPS)   # keep lost tracks ~6 s at any rate
                self.bytetrack = BYTETracker(cfg)
            except Exception as e:
                log.warning("ByteTrack unavailable, per-class cooldown instead: %s", e)
            log.info("YOLO loaded: %s, inference %d ms", path, self.infer_ms)
        except Exception as e:
            log.warning("YOLO unavailable, hazard loop off: %s", e)

    def track_ids(self, result, img) -> list[int | None]:
        ids: list[int | None] = [None] * len(result.boxes)
        if self.bytetrack is None or not len(result.boxes):
            return ids
        try:
            for row in self.bytetrack.update(result.boxes.cpu().numpy(), img):
                ids[int(row[-1])] = int(row[4])   # row = x1 y1 x2 y2 id score cls det_idx
        except Exception as e:
            log.debug("tracking failed: %s", e)
        return ids

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
        ids = self.track_ids(result, img)
        out = []
        for box, tid in zip(result.boxes, ids):
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            out.append(Box(names[int(box.cls)], float(box.conf), x1 / w, y1 / h, x2 / w, y2 / h, tid))
        return out

    def check(self, jpeg_b64: str, now: float | None = None) -> str | None:
        """Blocking; run in a thread. Returns a warning phrase or None."""
        self.last_run = time.time()
        return self.tracker.decide(self.detect(jpeg_b64), now if now is not None else time.time())


detector = HazardDetector()
