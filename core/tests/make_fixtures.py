"""Generate synthetic test fixtures: python -m tests.make_fixtures

  chair_walk/   25 frames, a magenta "chair" growing toward the wearer, centre x ~0.42
  clear_path/   150 frames, no magenta (false-warning check)
  scene_cut/    10 frames of one colour, then 10 of another (scene-change ingest)
  zoom_walk/    25 frames zooming into ultralytics' bus.jpg (real YOLO, when no real/chair_walk.mp4)
  room.jpg, keys_on_table.jpg, crosswalk.jpg   simple drawn scenes for offline beats
  audio/*.wav   demo phrases via macOS `say`, 8 kHz and 16 kHz mono s16le
  transcripts.json   sha1(pcm) -> phrase and file -> phrase
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent / "fixtures"
W, H = 640, 480
GREY = (128, 128, 128)
MAGENTA = (255, 0, 255)   # BGR

PHRASES = {
    "describe": "what's in front of me",
    "signal": "what does the signal say",
    "keys": "where did I put my keys",
    "email": "email Sam that I'm at the Palace of Fine Arts",
    "yes": "yes send it",
    "lost": "I'm lost",
    "sam": "this is my brother Sam",
}


def write(path: Path, img) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def frames_dir(name: str) -> Path:
    d = OUT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def chair_walk() -> None:
    d = frames_dir("chair_walk")
    for i in range(25):
        area = 0.03 * (10 ** (i / 24))          # geometric 0.03 -> 0.30
        side = area ** 0.5
        cx, bottom = 0.42, 0.95
        x1, x2 = (cx - side / 2) * W, (cx + side / 2) * W
        y1, y2 = (bottom - side) * H, bottom * H
        img = np.full((H, W, 3), GREY, np.uint8)
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), MAGENTA, -1)
        write(d / f"{i:04d}.jpg", img)


def clear_path() -> None:
    d = frames_dir("clear_path")
    rng = np.random.default_rng(0)
    for i in range(150):
        img = np.full((H, W, 3), GREY, np.uint8)
        off = int(20 * np.sin(i / 10))
        cv2.rectangle(img, (40 + off, 60), (160 + off, 200), (200, 120, 40), -1)     # distant blue box
        cv2.line(img, (0, 400), (W, 380), (90, 90, 90), 6)                         # floor edge
        img = np.clip(img.astype(np.int16) + rng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
        write(d / f"{i:04d}.jpg", img)


def scene_cut() -> None:
    d = frames_dir("scene_cut")
    for i in range(20):
        img = np.full((H, W, 3), (40, 40, 200) if i < 10 else (200, 160, 40), np.uint8)
        write(d / f"{i:04d}.jpg", img)


def zoom_walk() -> None:
    try:
        import ultralytics
        src = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
        base = cv2.imread(str(src))
    except Exception:
        base = None
    if base is None:
        print("  zoom_walk skipped (no ultralytics bus.jpg)")
        return
    d = frames_dir("zoom_walk")
    bh, bw = base.shape[:2]
    cx, cy = bw * 0.5, bh * 0.55
    for i in range(25):
        z = 1.0 + 1.2 * i / 24                     # zoom in 1x -> 2.2x
        cw, ch = bw / z, bw * 0.75 / z
        x1, y1 = int(max(0, cx - cw / 2)), int(max(0, cy - ch / 2))
        crop = base[y1:int(y1 + ch), x1:int(x1 + cw)]
        write(d / f"{i:04d}.jpg", cv2.resize(crop, (W, H)))


def scenes() -> None:
    room = np.full((H, W, 3), (170, 180, 190), np.uint8)
    cv2.rectangle(room, (0, 330), (W, H), (60, 90, 120), -1)                     # floor
    cv2.rectangle(room, (180, 240), (300, 420), (40, 60, 140), -1)               # chair
    cv2.rectangle(room, (420, 280), (620, 340), (30, 70, 110), -1)               # table
    cv2.putText(room, "ROOM", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    write(OUT / "room.jpg", room)

    keys = np.full((H, W, 3), (150, 160, 170), np.uint8)
    cv2.rectangle(keys, (60, 250), (580, 460), (40, 80, 130), -1)               # table top
    cv2.circle(keys, (320, 340), 22, (40, 200, 230), 4)                          # key ring
    cv2.rectangle(keys, (338, 332), (400, 346), (40, 200, 230), -1)              # key
    cv2.putText(keys, "KEYS", (290, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    write(OUT / "keys_on_table.jpg", keys)

    cross = np.full((H, W, 3), (120, 120, 120), np.uint8)
    for x in range(0, W, 80):
        cv2.rectangle(cross, (x, 380), (x + 40, H), (240, 240, 240), -1)        # zebra stripes
    cv2.rectangle(cross, (270, 60), (370, 240), (20, 20, 20), -1)               # signal head
    cv2.putText(cross, "WALK", (282, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    write(OUT / "crosswalk.jpg", cross)


def pcm_of(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes())


def audio() -> dict:
    table = {"by_sha1": {}, "by_file": {}}
    if not (shutil.which("say") and shutil.which("afconvert")):
        print("  audio skipped (needs macOS say + afconvert)")
        return table
    d = OUT / "audio"
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in PHRASES.items():
            aiff = Path(tmp) / f"{name}.aiff"
            subprocess.run(["say", "-o", str(aiff), text], check=True)
            for rate in (8000, 16000):
                wav = d / (f"{name}.wav" if rate == 8000 else f"{name}_16k.wav")
                subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", str(aiff), str(wav)],
                               check=True)
                table["by_sha1"][hashlib.sha1(pcm_of(wav)).hexdigest()] = text
                table["by_file"][wav.name] = text
    return table


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for step in (chair_walk, clear_path, scene_cut, zoom_walk, scenes):
        print(step.__name__)
        step()
    print("audio")
    table = audio()
    (OUT / "transcripts.json").write_text(json.dumps(table, indent=2) + "\n")
    print(f"done: {OUT} ({len(table['by_file'])} wavs)")


if __name__ == "__main__":
    sys.exit(main())
