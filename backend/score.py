# Score one model's answers against gold labels, and compare Jev vs Laya.

NOUL_YES = 0.5


def _round_score(value) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _noul_yes(value) -> bool | None:
    if value is None:
        return None
    return float(value) >= NOUL_YES


def question_verdict(question: dict, answer: dict | None, expected) -> dict:
    q_type = question.get("type")
    if not answer:
        return {"ok": False, "detail": "no answer"}

    if q_type == "choice":
        predicted = answer.get("choice")
        ok = predicted == expected
        return {"ok": ok, "predicted": predicted, "expected": expected}

    if q_type == "score":
        predicted = _round_score(answer.get("score"))
        ok = predicted == expected
        mae = None
        if answer.get("score") is not None and expected is not None:
            mae = abs(float(answer["score"]) - float(expected))
        return {
            "ok": ok,
            "predicted": predicted,
            "expected": expected,
            "raw_score": answer.get("score"),
            "mae": mae,
        }

    if q_type == "noul":
        predicted = _noul_yes(answer.get("noul"))
        ok = predicted == expected
        brier = None
        if answer.get("noul") is not None and expected is not None:
            target = 1.0 if expected else 0.0
            brier = (float(answer["noul"]) - target) ** 2
        return {
            "ok": ok,
            "predicted": predicted,
            "expected": expected,
            "raw_noul": answer.get("noul"),
            "brier": brier,
        }

    return {"ok": False, "detail": f"unknown type {q_type}"}


def score_case(case: dict, answers: dict | None) -> dict:
    questions = case["questions"]
    expected = case.get("expected") or {}
    per_question = {}
    hits = 0
    total = 0

    for name, question in questions.items():
        if name not in expected:
            continue
        total += 1
        verdict = question_verdict(question, (answers or {}).get(name), expected[name])
        per_question[name] = verdict
        if verdict.get("ok"):
            hits += 1

    return {
        "hits": hits,
        "total": total,
        "accuracy": (hits / total) if total else None,
        "per_question": per_question,
    }


def answers_agree(question: dict, left: dict | None, right: dict | None) -> bool | None:
    if not left or not right:
        return None
    q_type = question.get("type")
    if q_type == "choice":
        return left.get("choice") == right.get("choice")
    if q_type == "score":
        return _round_score(left.get("score")) == _round_score(right.get("score"))
    if q_type == "noul":
        return _noul_yes(left.get("noul")) == _noul_yes(right.get("noul"))
    return None


def summarize(rows: list[dict]) -> dict:
    by_model = {"jev": [], "laya": []}
    agreement_hits = 0
    agreement_total = 0

    for row in rows:
        for model_name in ("jev", "laya"):
            result = row.get(model_name)
            if result and result.get("ok"):
                by_model[model_name].append(result)

        jev_answers = (row.get("jev") or {}).get("answers") or {}
        laya_answers = (row.get("laya") or {}).get("answers") or {}
        questions = row.get("questions") or {}
        for name, question in questions.items():
            agreed = answers_agree(question, jev_answers.get(name), laya_answers.get(name))
            if agreed is None:
                continue
            agreement_total += 1
            if agreed:
                agreement_hits += 1

    summary = {}
    for model_name, results in by_model.items():
        latencies = [item["latency_ms"] for item in results]
        quality = [item["quality"]["accuracy"] for item in results if item.get("quality", {}).get("accuracy") is not None]
        summary[model_name] = {
            "runs": len(results),
            "mean_ms": _mean(latencies),
            "p50_ms": _percentile(latencies, 50),
            "min_ms": min(latencies) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
            "accuracy": _mean(quality),
        }

    summary["agreement"] = (agreement_hits / agreement_total) if agreement_total else None
    summary["agreement_hits"] = agreement_hits
    summary["agreement_total"] = agreement_total
    return summary


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]
