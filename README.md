# decisionmakertest

Quick bench comparing **Jev** (TypeSafe, hosted) and **Laya** (local) on the same typed decisions.

Same state, same questions (`choice` / `score` / yes-no). Times them, checks answers against gold labels, and has a tiny dungeon game where both play live.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For GPU Laya (Linux/NVIDIA), install a CUDA torch build first, e.g.:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add a Jev key:

- `TYPESAFE_API_KEY` from [console.typesafe.ai](https://console.typesafe.ai/settings/keys), or
- `JEV_AGENT_KEY` from [jev-agent.com](https://jev-agent.com/api-access)

Laya defaults to CUDA. On a small GPU, `LAYA_SUBFOLDER=multilingual` (already in the example) is the faster checkpoint.

## Run

```bash
# Linux / mac
source .venv/bin/activate
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend --reload-dir frontend
```

Windows: `.\start.ps1`

Open http://127.0.0.1:8000

## What’s in the UI

- **Speed race** — same email, many rounds, bar chart
- **Live game** — Ashen Gate, both models walk the same 8 rooms
- **Answer quality** — labeled cases, run Jev / Laya / both
- **Try your own** — paste a message + question schema

First Laya load downloads weights from Hugging Face (~hundreds of MB).
