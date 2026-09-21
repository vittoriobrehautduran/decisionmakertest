# App settings: Jev is a hosted API, Laya runs locally from Hugging Face weights.
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

HF_CACHE = ROOT / "hf_cache"
HF_CACHE.mkdir(exist_ok=True)
os.environ.setdefault("HF_HOME", str(HF_CACHE))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HF_CACHE))
# transformers can deadlock on import if TensorFlow is installed.
os.environ.setdefault("USE_TF", "0")


def _clean(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


TYPESAFE_API_KEY = _clean(os.getenv("TYPESAFE_API_KEY"))
JEV_AGENT_KEY = _clean(os.getenv("JEV_AGENT_KEY"))
JEV_MODEL = _clean(os.getenv("JEV_MODEL")) or "jev-1.13.0"
LAYA_DEVICE = _clean(os.getenv("LAYA_DEVICE")) or "cpu"
LAYA_MODEL = _clean(os.getenv("LAYA_MODEL")) or "convaiinnovations/laya"


def jev_config() -> dict:
    # Official TypeSafe key wins if both are present.
    if TYPESAFE_API_KEY:
        return {
            "configured": True,
            "provider": "typesafe",
            "base_url": _clean(os.getenv("JEV_BASE_URL")) or "https://api.typesafe.ai",
            "api_key": TYPESAFE_API_KEY,
            "model": JEV_MODEL,
        }
    if JEV_AGENT_KEY:
        return {
            "configured": True,
            "provider": "jev-agent",
            "base_url": _clean(os.getenv("JEV_BASE_URL")) or "https://jev-agent.com",
            "api_key": JEV_AGENT_KEY,
            "model": JEV_MODEL,
        }
    return {
        "configured": False,
        "provider": None,
        "base_url": None,
        "api_key": "",
        "model": JEV_MODEL,
    }
