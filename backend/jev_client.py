# Call hosted Jev (TypeSafe official API, or jev-agent.com if you only have a free key).
import time

import httpx

from backend.config import jev_config


class JevNotConfigured(RuntimeError):
    pass


def _endpoint(cfg: dict) -> str:
    if cfg["provider"] == "jev-agent":
        return f"{cfg['base_url'].rstrip('/')}/api/v1/systemone"
    return f"{cfg['base_url'].rstrip('/')}/v1/systemone"


def status() -> dict:
    cfg = jev_config()
    return {
        "configured": cfg["configured"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
    }


def decide(state, questions: dict) -> dict:
    cfg = jev_config()
    if not cfg["configured"]:
        raise JevNotConfigured(
            "No Jev key set. Add TYPESAFE_API_KEY or JEV_AGENT_KEY to .env"
        )

    payload = {
        "model": cfg["model"],
        "state": state,
        "questions": questions,
    }
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    with httpx.Client(timeout=45.0) as client:
        response = client.post(_endpoint(cfg), json=payload, headers=headers)
    latency_ms = (time.perf_counter() - started) * 1000

    if response.status_code >= 400:
        detail = response.text[:800]
        raise RuntimeError(f"Jev HTTP {response.status_code}: {detail}")

    body = response.json()
    return {
        "ok": True,
        "model": "jev",
        "model_id": body.get("model") or cfg["model"],
        "provider": cfg["provider"],
        "latency_ms": round(latency_ms, 1),
        "answers": _normalize_answers(body.get("answers") or {}),
        "usage": body.get("usage"),
        "raw": body,
    }


def _normalize_answers(answers: dict) -> dict:
    # Keep the three primitives in one shape so the UI can compare them to Laya.
    out = {}
    for name, answer in answers.items():
        item = dict(answer) if isinstance(answer, dict) else {"value": answer}
        q_type = item.get("type")
        if not q_type:
            if "choice" in item:
                q_type = "choice"
            elif "score" in item:
                q_type = "score"
            elif "noul" in item:
                q_type = "noul"
            item["type"] = q_type
        out[name] = item
    return out
