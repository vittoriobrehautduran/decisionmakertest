# Load Laya locally from Hugging Face and run the same typed questions as Jev.
import threading
import time
import traceback

from backend.config import LAYA_DEVICE, LAYA_MODEL, LAYA_SUBFOLDER

_lock = threading.Lock()
_ready = threading.Event()
_agent = None
_state = {
    "loaded": False,
    "loading": False,
    "error": None,
    "model": LAYA_MODEL if not LAYA_SUBFOLDER else f"{LAYA_MODEL}/{LAYA_SUBFOLDER}",
    "device": LAYA_DEVICE,
    "message": "not loaded",
}

# Same shape as the playground so warmup picks CUDA kernels for the real calls.
_WARMUP_STATE = {
    "from": "user@acme.com",
    "subject": "Duplicate charge on invoice #4411",
    "body": "Hi, we were billed twice for March. Please refund the duplicate today or we will cancel our plan.",
}
_WARMUP_QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": "Which department should handle this request?",
        "criteria": {
            "billing": "invoices, payments, refunds, duplicate charges",
            "technical": "bugs, outages, login issues, system errors",
            "sales": "pricing, new contracts, upgrades, demos",
            "other": "everything else",
        },
    },
    "urgency": {
        "type": "score",
        "instructions": "How urgent is this request?",
        "criteria": ["not urgent, can wait", "should be handled soon", "critical deadline or blocking issue"],
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated does the customer appear?",
        "criteria": ["calm, just stating facts", "frustrated but civil", "very angry, strong language"],
    },
    "churn_risk": {
        "type": "noul",
        "instructions": "Does the user threaten to cancel, leave, or take their business elsewhere?",
        "criteria": {
            "true": "mentions cancelling, leaving, or switching providers",
            "false": "no cancellation or leaving intent",
        },
    },
    "refund_requested": {
        "type": "noul",
        "instructions": "Does the user explicitly request a refund or money back?",
        "criteria": {
            "true": "explicitly asks for a refund or chargeback",
            "false": "does not ask for a refund",
        },
    },
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


def _configure_fast_cuda(torch) -> None:
    # Turing (T1000) has no FlashAttention; mem-efficient SDPA is the fast path.
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(True)
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = True
    torch.set_float32_matmul_precision("high")


def _speed_up_agent(agent, torch) -> None:
    # Keep weights in fp16 so each step does not read fp32 from VRAM and cast.
    if agent.device.type == "cuda":
        _configure_fast_cuda(torch)
        agent.model.half()
        agent.dtype = torch.float16
        try:
            agent.model.encoder.set_attn_implementation("sdpa")
        except Exception:
            pass

    orig_forward = agent.model.forward

    def timed_forward(*args, **kwargs):
        if agent.device.type == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        out = orig_forward(*args, **kwargs)
        if agent.device.type == "cuda":
            torch.cuda.synchronize()
        _state["last_gpu_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return out

    agent.model.forward = timed_forward


def _warmup(agent, torch) -> None:
    # Run the real playground shape twice so CUDA caches those kernels.
    agent.predict(_WARMUP_STATE, _WARMUP_QUESTIONS)
    if agent.device.type == "cuda":
        torch.cuda.synchronize()
    agent.predict(_WARMUP_STATE, _WARMUP_QUESTIONS)
    if agent.device.type == "cuda":
        torch.cuda.synchronize()


def _load_blocking() -> None:
    global _agent
    try:
        import laya
        import torch

        device = LAYA_DEVICE
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model_label = LAYA_MODEL if not LAYA_SUBFOLDER else f"{LAYA_MODEL}/{LAYA_SUBFOLDER}"
        _state["model"] = model_label
        _state["device"] = device
        _state["message"] = f"loading {model_label} on {device}..."

        agent = laya.load(LAYA_MODEL, device=device, subfolder=LAYA_SUBFOLDER or None)
        _speed_up_agent(agent, torch)
        _state["message"] = "warming up..."
        _warmup(agent, torch)

        param = next(agent.model.parameters())
        dtype_name = str(param.dtype).replace("torch.", "")
        attn = getattr(agent.model.encoder.config, "_attn_implementation", None)
        _state["dtype"] = dtype_name
        _state["attn"] = attn

        with _lock:
            _agent = agent
            _state["loaded"] = True
            _state["loading"] = False
            _state["message"] = f"ready on {device} ({dtype_name}, {attn})"
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

    import torch

    started = time.perf_counter()
    with torch.inference_mode():
        result = _agent.predict(state, questions)
    if _state.get("device") == "cuda":
        torch.cuda.synchronize()
    latency_ms = (time.perf_counter() - started) * 1000

    answers = result.get("answers") if isinstance(result, dict) else result
    return {
        "ok": True,
        "model": "laya",
        "model_id": _state.get("model") or LAYA_MODEL,
        "provider": "local",
        "device": _state["device"],
        "latency_ms": round(latency_ms, 1),
        "gpu_ms": _state.get("last_gpu_ms"),
        "answers": answers or {},
        "routing": result.get("routing") if isinstance(result, dict) else None,
        "raw": result,
    }
