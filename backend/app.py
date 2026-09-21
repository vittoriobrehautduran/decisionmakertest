# FastAPI app that runs the same typed-decision cases against Jev and Laya.
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import jev_client, laya_client
from backend.cases import list_cases
from backend.score import score_case, summarize

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Jev vs Laya bench")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    case_ids: list[str] | None = None
    models: list[str] = Field(default_factory=lambda: ["jev", "laya"])


class PlayRequest(BaseModel):
    state: object
    questions: dict
    models: list[str] = Field(default_factory=lambda: ["jev", "laya"])


@app.get("/api/status")
def api_status():
    return {
        "jev": jev_client.status(),
        "laya": laya_client.status(),
    }


@app.post("/api/laya/load")
def api_laya_load():
    return laya_client.start_load()


@app.get("/api/cases")
def api_cases():
    return list_cases()


@app.post("/api/run")
def api_run(body: RunRequest):
    wanted = body.case_ids
    cases = list_cases()
    if wanted:
        cases = [case for case in cases if case["id"] in wanted]
        missing = set(wanted) - {case["id"] for case in cases}
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown cases: {sorted(missing)}")

    rows = [_run_case(case, body.models) for case in cases]
    return {"rows": rows, "summary": summarize(rows)}


@app.post("/api/play")
def api_play(body: PlayRequest):
    row = {
        "id": "playground",
        "title": "Playground",
        "group": "custom",
        "state": body.state,
        "questions": body.questions,
        "expected": {},
    }
    result = _run_case(row, body.models)
    return {"row": result, "summary": summarize([result])}


def _run_case(case: dict, models: list[str]) -> dict:
    row = {
        "id": case["id"],
        "title": case["title"],
        "group": case.get("group"),
        "state": case["state"],
        "questions": case["questions"],
        "expected": case.get("expected") or {},
        "jev": None,
        "laya": None,
    }

    for name in models:
        try:
            if name == "jev":
                result = jev_client.decide(case["state"], case["questions"])
            elif name == "laya":
                result = laya_client.decide(case["state"], case["questions"])
            else:
                result = {"ok": False, "error": f"unknown model {name}"}
        except Exception as exc:
            result = {"ok": False, "model": name, "error": str(exc)}

        if result.get("ok"):
            result["quality"] = score_case(case, result.get("answers"))
        row[name] = result

    return row


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
