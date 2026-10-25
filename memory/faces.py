"""Recognize people the wearer has introduced, by face, entirely on this laptop.

Claude never identifies people from faces, so this uses OpenCV's YuNet (finds faces) and SFace (turns a face into 128
numbers) from the OpenCV model zoo. A person is enrolled only when the wearer names them ("this is my brother Sam");
strangers are never stored or identified. Face crops and signatures live in memory/faces/, never in SpacetimeDB, and
are deleted when the person is forgotten. If OpenCV or the models are missing, nothing is recognized and the rest of
memory works as before.
"""
import logging
import re
import threading
import urllib.request
import zlib
from pathlib import Path

log = logging.getLogger("memory")

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {  # file -> (url, smallest plausible size in bytes, to catch a failed or partial download)
    "face_detection_yunet_2023mar.onnx": (f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx", 200_000),
    "face_recognition_sface_2021dec.onnx": (f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx", 30_000_000),
}
DETECT_SCORE = 0.8   # YuNet confidence for a face to count
# shortcut: OpenCV's recommended cosine threshold for SFace (0.363); tune on real photos of the wearer's people.
MATCH_SCORE = 0.363
MAX_SAMPLES = 5      # signatures kept per person: each re-introduction adds a view, the oldest is dropped
FULL_SIZE = 200 * 200  # a face this big is already plenty to recognise: past it, size stops counting
MAX_SIDE = 960       # bigger frames are shrunk first, faces are found just as well and it is faster


# ---- pure helpers (no models needed) ------------------------------------------------------------

def quality(row, width: int) -> float:
    """How identifying a view is: big enough, confidently found, facing the camera (the nose midway between the eyes) and not cut
    off by the frame edge. Rows are YuNet's x, y, w, h, right eye, left eye, nose, 2 mouth corners (x, y each), score."""
    eye_gap = abs(row[6] - row[4]) or 1.0
    turn = abs(row[8] - (row[4] + row[6]) / 2) / eye_gap  # 0 facing the camera, 0.5 or more in profile
    frontal = max(0.1, 1 - 1.5 * turn)
    cut = 0.3 if row[0] < 0 or row[0] + row[2] > width else 1.0
    return min(row[2] * row[3], FULL_SIZE) * row[14] * frontal * cut


def best_face(rows, width: int):
    """The most identifying face in a frame (see quality), or None when there are none."""
    return max(rows, key=lambda r: quality(r, width), default=None)


def where(row, width: int) -> str:
    """'on the left', 'ahead' or 'on the right', from where the face sits across the frame."""
    cx = (row[0] + row[2] / 2) / width
    return "on the left" if cx < 0.35 else "on the right" if cx > 0.65 else "ahead"


def cosine(a, b) -> float:
    import numpy as np
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


def best_name(feature, enrolled: dict, threshold: float = MATCH_SCORE):
    """(name, score) of the enrolled person this face is most like, or None if nobody reaches the threshold."""
    best = max(((name, max(cosine(feature, s) for s in samples)) for name, samples in enrolled.items() if len(samples)),
               key=lambda x: x[1], default=None)
    return best if best and best[1] >= threshold else None


def file_stem(name: str) -> str:
    """A safe file name for a person: 'Mary-Ann' and 'Mary Ann' differ by the hash, odd characters are dropped."""
    return f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'person'}-{zlib.crc32(name.encode()):08x}"


# ---- the service --------------------------------------------------------------------------------

class Faces:
    def __init__(self, face_dir: Path, model_dir: Path) -> None:
        self.face_dir, self.model_dir = face_dir, model_dir
        self.ready = False                    # True once OpenCV and both models are loaded
        self.enrolled: dict[str, list] = {}   # name -> signatures
        self.lock = threading.Lock()          # OpenCV's detector keeps state (the input size): one call at a time

    def load(self) -> None:
        """Download the models if needed, load them and the saved signatures. Blocking: call from a thread."""
        try:
            import cv2
            import numpy as np  # noqa: F401
        except ImportError:
            log.warning("faces: OpenCV isn't installed (pip install opencv-python-headless): no face recognition")
            return
        try:
            self.model_dir.mkdir(exist_ok=True)
            for fname, (url, min_size) in MODELS.items():
                path = self.model_dir / fname
                if not path.exists() or path.stat().st_size < min_size:
                    log.info("faces: downloading %s", fname)
                    tmp = path.with_suffix(".part")
                    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as out:
                        out.write(r.read())
                    if tmp.stat().st_size < min_size:
                        tmp.unlink()
                        raise RuntimeError(f"{fname} downloaded too small")
                    tmp.replace(path)
            self.det = cv2.FaceDetectorYN.create(str(self.model_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320),
                                                 DETECT_SCORE, 0.3, 5000)
            self.rec = cv2.FaceRecognizerSF.create(str(self.model_dir / "face_recognition_sface_2021dec.onnx"), "")
        except Exception as e:
            log.warning("faces: models unavailable, no face recognition: %r", e)
            return
        self.face_dir.mkdir(exist_ok=True)
        import numpy as np
        for f in self.face_dir.glob("*.npz"):
            d = np.load(f, allow_pickle=False)
            self.enrolled[str(d["name"])] = list(d["feats"])
        self.ready = True
        log.info("faces: ready, %d people enrolled", len(self.enrolled))

    def _image(self, jpeg: bytes):
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        s = MAX_SIDE / max(img.shape[:2])
        return cv2.resize(img, None, fx=s, fy=s) if s < 1 else img

    def _faces(self, img) -> list:
        h, w = img.shape[:2]
        with self.lock:
            self.det.setInputSize((w, h))
            _, rows = self.det.detect(img)
        return [] if rows is None else list(rows)

    def _signature(self, img, row):
        with self.lock:
            crop = self.rec.alignCrop(img, row)
            return crop, self.rec.feature(crop)[0]

    def enroll(self, name: str, jpeg: bytes) -> bool:
        """Save the clearest face in this frame as `name`'s signature (and the crop). False if there's no usable face."""
        if not self.ready:
            return False
        img = self._image(jpeg)
        row = best_face(self._faces(img), img.shape[1]) if img is not None else None
        if row is None:
            log.info("faces: no face to enroll for %s", name)
            return False
        import cv2
        import numpy as np
        crop, feat = self._signature(img, row)
        samples = (self.enrolled.get(name, []) + [feat])[-MAX_SAMPLES:]
        self.enrolled[name] = samples
        stem = file_stem(name)
        np.savez(self.face_dir / f"{stem}.npz", name=name, feats=np.array(samples))
        cv2.imwrite(str(self.face_dir / f"{stem}.jpg"), crop)
        log.info("faces: enrolled %s (%d views)", name, len(samples))
        return True

    def match(self, jpeg: bytes) -> list[tuple[str, float, str]]:
        """Enrolled people seen in this frame as (name, score, 'on the left'|'ahead'|'on the right'), left to right."""
        if not self.ready or not self.enrolled:
            return []
        img = self._image(jpeg)
        if img is None:
            return []
        found: dict[str, tuple[float, str, float]] = {}
        for row in self._faces(img):
            hit = best_name(self._signature(img, row)[1], self.enrolled)
            if hit and (hit[0] not in found or hit[1] > found[hit[0]][0]):
                found[hit[0]] = (hit[1], where(row, img.shape[1]), row[0])
        return [(n, round(s, 2), pos) for n, (s, pos, _x) in sorted(found.items(), key=lambda kv: kv[1][2])]

    def forget(self, name: str) -> None:
        self.enrolled.pop(name, None)
        for ext in ("npz", "jpg"):
            (self.face_dir / f"{file_stem(name)}.{ext}").unlink(missing_ok=True)

    def forget_all(self) -> None:
        for name in list(self.enrolled):
            self.forget(name)
        for f in self.face_dir.glob("*") if self.face_dir.exists() else []:  # anything left from a name this run never saw
            f.unlink(missing_ok=True)
