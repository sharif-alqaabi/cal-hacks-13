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

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2025-04-16")
CARTESIA_STT_MODEL = os.getenv("CARTESIA_STT_MODEL", "ink-2")       # TODO confirm exact model id
CARTESIA_TTS_MODEL = os.getenv("CARTESIA_TTS_MODEL", "sonic-3.5")   # TODO confirm exact model id
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
TTS_RATE = int(os.getenv("TTS_RATE", "24000"))

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
JEV_CONFIDENCE_THRESHOLD = float(os.getenv("JEV_CONFIDENCE_THRESHOLD", "0.6"))

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8001")
BROWSER_URL = os.getenv("BROWSER_URL", "http://127.0.0.1:8002")
SERVICE_TIMEOUT_S = float(os.getenv("SERVICE_TIMEOUT_S", "4"))
INGEST_EVERY_S = float(os.getenv("INGEST_EVERY_S", "3"))

HAZARDS_ENABLED = _bool("HAZARDS_ENABLED", True)
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
HAZARD_FPS = float(os.getenv("HAZARD_FPS", "5"))
HAZARD_COOLDOWN_S = float(os.getenv("HAZARD_COOLDOWN_S", "3"))
DEMO_MODE = _bool("DEMO_MODE", False)   # stricter hazard gating for a busy table
