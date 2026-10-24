"""All settings come from env / .env. Nothing secret lives in the repo."""
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "claude-haiku-5-5")      # describe / signal
ROUTER_FALLBACK_MODEL = os.getenv("ROUTER_FALLBACK_MODEL", "claude-sonnet-5-5")
SIGNAL_MODEL = os.getenv("SIGNAL_MODEL", "") or VISION_MODEL
ROUTER_FALLBACK_TIMEOUT_S = float(os.getenv("ROUTER_FALLBACK_TIMEOUT_S", "2"))
VISION_TIMEOUT_S = float(os.getenv("VISION_TIMEOUT_S", "6"))
CHAT_TIMEOUT_S = float(os.getenv("CHAT_TIMEOUT_S", "4"))

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2026-08-14")
CARTESIA_STT_MODEL = os.getenv("CARTESIA_STT_MODEL", "ink-2")
CARTESIA_TTS_MODEL = os.getenv("CARTESIA_TTS_MODEL", "sonic-3.5")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
TTS_RATE = int(os.getenv("TTS_RATE", "24000"))
TTS_TIMEOUT_S = float(os.getenv("TTS_TIMEOUT_S", "4"))
STT_FINISH_TIMEOUT_S = float(os.getenv("STT_FINISH_TIMEOUT_S", "3"))
STT_KEYTERMS = [k.strip() for k in os.getenv("STT_KEYTERMS", "").split(",") if k.strip()]
SAY_SPLIT = _bool("SAY_SPLIT", True)   # one say per sentence; false joins a reply into one say (Q2)

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
JEV_CONFIDENCE_THRESHOLD = float(os.getenv("JEV_CONFIDENCE_THRESHOLD", "0.6"))
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
JEV_URL = os.getenv("JEV_URL", "https://api.typesafe.ai/v1/systemone")
JEV_TIMEOUT_S = float(os.getenv("JEV_TIMEOUT_S", "0.8"))

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8001")
BROWSER_URL = os.getenv("BROWSER_URL", "http://127.0.0.1:8002")
SERVICE_TIMEOUT_S = float(os.getenv("SERVICE_TIMEOUT_S", "4"))
INGEST_EVERY_S = float(os.getenv("INGEST_EVERY_S", "3"))
INGEST_TIMEOUT_S = float(os.getenv("INGEST_TIMEOUT_S", "2"))
SCENE_CHANGE_THRESHOLD = float(os.getenv("SCENE_CHANGE_THRESHOLD", "18"))

HAZARDS_ENABLED = _bool("HAZARDS_ENABLED", True)
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
HAZARD_FPS = float(os.getenv("HAZARD_FPS", "5"))
HAZARD_COOLDOWN_S = float(os.getenv("HAZARD_COOLDOWN_S", "10"))   # only when YOLO tracking is unavailable
DEMO_MODE = _bool("DEMO_MODE", False)   # stricter hazard gating for a busy table
HAZARD_IMGSZ = int(os.getenv("HAZARD_IMGSZ", "320"))

MIRROR_FRAME_FPS = float(os.getenv("MIRROR_FRAME_FPS", "2"))

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(ROOT / "cache")))
LOG_DIR = Path(os.getenv("LOG_DIR", str(ROOT / "logs")))
