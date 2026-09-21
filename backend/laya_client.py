# Load Laya locally from Hugging Face and run the same typed questions as Jev.
import threading
import time
import traceback

from backend.config import LAYA_DEVICE, LAYA_MODEL

_lock = threading.Lock()
_ready = threading.Event()
_agent = None
_state = {
    "loaded": False,
    "loading": False,
    "error": None,
    "model": LAYA_MODEL,
    "device": LAYA_DEVICE,
    "message": "not loaded",
}


def status() -> dict:
    return dict(_state)


def start_load() -> dict:
    # Return immediately so the UI can poll /api/status while weights download.
    with _lock:
        if _state["loaded"] or _state["loading"]:
            return status()
        _state["loading"] = True
        _state["error"] = None
        _state["message"] = "downloading / loading weights..."
        _ready.clear()
        thread = threading.Thread(target=_load_blocking, daemon=True)
        thread.start()
    return status()


def load() -> dict:
    start_load()
    _ready.wait()
    if _state["error"]:
        raise RuntimeError(_state["error"])
    return status()


def _load_blocking() -> None:
    global _agent
    try:
        import laya
        import torch

        device = LAYA_DEVICE
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        _state["device"] = device
        _state["message"] = f"loading {LAYA_MODEL} on {device}..."

        agent = laya.load(LAYA_MODEL, device=device)
        # Warmup so the first timed test is not the compile/download hit.
        warmup_state = {"body": "Thanks, that is all."}
        warmup_questions = {
            "ok": {
                "type": "noul",
                "instructions": "Is this a short thank-you message?",
            }
        }
        _state["message"] = "warming up..."
        agent.predict(warmup_state, warmup_questions)

        with _lock:
            _agent = agent
            _state["loaded"] = True
            _state["loading"] = False
            _state["message"] = f"ready on {device}"
            _state["error"] = None
    except Exception as exc:
        with _lock:
            _agent = None
            _state["loaded"] = False
            _state["loading"] = False
            _state["error"] = f"{exc}\n{traceback.format_exc()}"
            _state["message"] = "load failed"
    finally:
        _ready.set()


def decide(state, questions: dict) -> dict:
    if not _state["loaded"] or _agent is None:
        load()

    started = time.perf_counter()
    result = _agent.predict(state, questions)
    latency_ms = (time.perf_counter() - started) * 1000

    answers = result.get("answers") if isinstance(result, dict) else result
    return {
        "ok": True,
        "model": "laya",
        "model_id": LAYA_MODEL,
        "provider": "local",
        "device": _state["device"],
        "latency_ms": round(latency_ms, 1),
        "answers": answers or {},
        "routing": result.get("routing") if isinstance(result, dict) else None,
        "raw": result,
    }
