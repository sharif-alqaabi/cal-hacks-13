"""Settings from browser/.env. Read as module attributes at call time so tests can patch them."""
import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")   # into os.environ: Jev Ultrafast reads its keys from there


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


FAKE = _flag("BROWSER_FAKE")

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
TEXT_MODEL_API_KEY = os.getenv("TEXT_MODEL_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
READBACK_MODEL = os.getenv("READBACK_MODEL", "claude-sonnet-5-5")
WORK_MODEL = os.getenv("WORK_MODEL", "claude-sonnet-5-5")

DEMO_CONTACTS = os.getenv("DEMO_CONTACTS", "Sam=sam.calhacks.demo@gmail.com")
GMAIL_ACCOUNT_INDEX = int(os.getenv("GMAIL_ACCOUNT_INDEX", "0"))
UNDO_SEND_S = float(os.getenv("UNDO_SEND_S", "5"))
SENT_POLL_S = float(os.getenv("SENT_POLL_S", "8"))
GMAIL_PREFILL = _flag("GMAIL_PREFILL")
VERIFY_CANCEL = _flag("VERIFY_CANCEL")   # after "cancel", check Sent is still clean (acceptance runs)

TASK_BUDGET_S = float(os.getenv("TASK_BUDGET_S", "32"))
CONFIRM_BUDGET_S = float(os.getenv("CONFIRM_BUDGET_S", "34"))
LOOKUP_MAX_STEPS = int(os.getenv("LOOKUP_MAX_STEPS", "6"))
WEB_MAX_STEPS = int(os.getenv("WEB_MAX_STEPS", "8"))
TASK_TTL_S = float(os.getenv("TASK_TTL_S", "600"))

LOG_DIR = Path(os.getenv("BROWSER_LOG_DIR", str(HERE / "logs")))
