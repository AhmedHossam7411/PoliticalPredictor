"""Speech Lab: stress-test the predictor's LTA accuracy with speeches of known traits.

Pick a target level per trait -> the LLM writes a speech at those levels ->
both of the predictor's scorers rate it -> target vs measured, logged per run.

Run from the repo root:
    python -m uvicorn tools.speech_lab.server:app --port 8100
then open http://127.0.0.1:8100. Local tool: no login, binds to localhost.
Uses the same AI settings as the predictor (GROQ_API_KEY or LLM_*).
"""
from __future__ import annotations

import csv
import io
import json
import math
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from predictor import llm
from predictor.lta import RATIO_TRAITS
from predictor.score import analyze_with_bands, default_norm, ratio_band

from .generate import LANGUAGES, TRAITS, generate
from .highlight import scorer_spans

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results" / "runs.jsonl"

# Hermann's bands are +/-1 SD around the norm group, i.e. the 16th/84th
# percentiles; targets are banded the same way so the comparison is fair.
# CC, SC and TASK aren't normed: their two lists compete, so 50 is the dividing line.
HIGH_CUT, LOW_CUT = 84, 16

app = FastAPI(title="Speech Lab")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


def band_of(trait: str, v: float) -> str:
    if trait in RATIO_TRAITS:
        return ratio_band(trait, v / 100)
    return "High" if v > HIGH_CUT else "Low" if v < LOW_CUT else "Moderate"


def percentile(value: float, mean: float, std: float) -> float:
    """Where a raw dictionary value sits in the norm group, 0-100 (normal approx.)."""
    if std == 0:
        return 50.0
    return 50.0 * (1 + math.erf((value - mean) / (std * math.sqrt(2))))


def _llm_error(exc: Exception) -> HTTPException:
    if isinstance(exc, llm.LLMNotConfigured):
        return HTTPException(503, str(exc))
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return HTTPException(429, "AI rate limit reached; wait a minute and retry.")
    return HTTPException(502, f"AI call failed: {type(exc).__name__}: {exc}"[:300])


class Targets(BaseModel):
    targets: dict[str, int] = Field(..., description="Trait -> 0..100")
    language: str = "en"
    topic: str = ""
    words: int = Field(600, ge=150, le=1500)


class ScoreReq(BaseModel):
    text: str = Field(..., min_length=1)
    targets: dict[str, int]
    language: str = "en"
    topic: str = ""
    meta: dict = {}  # from /api/generate: model, title, markers, intended spans
    edited: bool = False


def _check_targets(targets: dict[str, int]) -> None:
    missing = [t for t in TRAITS if t not in targets]
    if missing or any(not 0 <= targets[t] <= 100 for t in TRAITS):
        raise HTTPException(422, f"Need all of {TRAITS} in 0..100 (missing {missing}).")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    return {"traits": TRAITS, "languages": LANGUAGES, "llm_available": llm.available(),
            "model": llm._model(), "cuts": {"high": HIGH_CUT, "low": LOW_CUT}}


@app.post("/api/generate")
def api_generate(req: Targets) -> dict:
    _check_targets(req.targets)
    if req.language not in LANGUAGES:
        raise HTTPException(422, f"language must be one of {list(LANGUAGES)}")
    try:
        return generate(req.targets, req.language, req.topic, req.words)
    except Exception as exc:  # noqa: BLE001 -- every AI failure becomes a clear HTTP error
        raise _llm_error(exc)


@app.post("/api/score")
def api_score(req: ScoreReq) -> dict:
    """Score a speech with both scorers, compare with the targets, log the run."""
    _check_targets(req.targets)
    dict_res = analyze_with_bands(req.text)
    lang = dict_res["input"]["language"]
    norm = default_norm(lang)

    ai, ai_error = None, None
    try:
        ai = llm.score_llm(req.text)
    except Exception as exc:  # noqa: BLE001 -- report it, still return dictionary results
        ai_error = _llm_error(exc).detail

    rows = []
    for t in TRAITS:
        tr = dict_res["lta"]["traits"][t]
        target = req.targets[t]
        # The evidence-weighted value: a list's share of the hits, or for one-list
        # traits a percentile against the norm group, as the predictor bands it.
        pct = 100 * tr["adjusted"] if t in RATIO_TRAITS \
            else percentile(tr["adjusted"], norm[t]["mean"], norm[t]["std"])
        row = {"trait": t, "target": target, "target_band": band_of(t, target),
               "dict_value": tr["value"], "dict_pct": round(pct, 1), "dict_band": tr["band"],
               "dict_confidence": tr["confidence"]}
        if ai:
            a = ai["traits"].get(t, {})
            score = a.get("score")
            # Band the AI's 0-100 score with the same cut-offs as the targets;
            # its own label (ai_label) uses looser, unstated ones.
            row.update(ai_score=score, ai_label=a.get("band"),
                       ai_band=band_of(t, score) if isinstance(score, (int, float)) else None,
                       ai_rationale=a.get("rationale", ""))
        rows.append(row)

    def summary(key: str, band_key: str) -> dict | None:
        vals = [(r["target"], r[key], r["target_band"], r[band_key]) for r in rows
                if isinstance(r.get(key), (int, float))]
        if not vals:
            return None
        return {"mae": round(sum(abs(a - b) for a, b, _, _ in vals) / len(vals), 1),
                "band_agree": sum(tb == mb for _, _, tb, mb in vals), "n": len(vals)}

    run = {
        "id": uuid.uuid4().hex[:10], "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "language": req.language, "detected": dict_res["input"],
        "topic": req.topic, "words": len(req.text.split()), "edited": req.edited,
        "gen_model": req.meta.get("model"), "ai_model": ai.get("model") if ai else None,
        "rows": rows, "dict_summary": summary("dict_pct", "dict_band"),
        "ai_summary": summary("ai_score", "ai_band"), "ai_error": ai_error,
        "markers": f"{req.meta.get('markers_found', '')}/{req.meta.get('markers_total', '')}",
        "text": req.text,
    }
    RUNS.parent.mkdir(exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run, ensure_ascii=False) + "\n")
    return {**run, "scorer_spans": scorer_spans(req.text),
            "ai_style": ai.get("leadership_style") if ai else None}


def _load_runs() -> list[dict]:
    if not RUNS.exists():
        return []
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines() if line]


@app.get("/api/runs")
def runs() -> list[dict]:
    """Every logged run, newest first, without the speech text."""
    return [{k: v for k, v in r.items() if k != "text"} for r in reversed(_load_runs())]


@app.get("/api/runs.csv")
def runs_csv() -> PlainTextResponse:
    """One row per run: targets and both scorers' results per trait, plus the speech."""
    out = io.StringIO()
    cols = ["id", "time", "language", "detected_dialect", "words", "edited",
            "gen_model", "ai_model", "dict_mae", "dict_band_agree", "ai_mae", "ai_band_agree"]
    for t in TRAITS:
        cols += [f"{t}_target", f"{t}_target_band", f"{t}_dict_pct", f"{t}_dict_band",
                 f"{t}_ai", f"{t}_ai_band"]
    cols.append("text")
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    for r in _load_runs():
        ds, ai = r.get("dict_summary") or {}, r.get("ai_summary") or {}
        row = {"id": r["id"], "time": r["time"], "language": r["language"],
               "detected_dialect": r["detected"].get("dialect") or r["detected"]["language"],
               "words": r["words"], "edited": r["edited"], "gen_model": r["gen_model"],
               "ai_model": r["ai_model"], "dict_mae": ds.get("mae"),
               "dict_band_agree": ds.get("band_agree"), "ai_mae": ai.get("mae"),
               "ai_band_agree": ai.get("band_agree"), "text": r["text"]}
        for x in r["rows"]:
            t = x["trait"]
            row.update({f"{t}_target": x["target"], f"{t}_target_band": x["target_band"],
                        f"{t}_dict_pct": x["dict_pct"], f"{t}_dict_band": x["dict_band"],
                        f"{t}_ai": x.get("ai_score"), f"{t}_ai_band": x.get("ai_band")})
        w.writerow(row)
    # BOM so Excel opens the Arabic text correctly.
    return PlainTextResponse("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=speech_lab_runs.csv"})


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    for r in _load_runs():
        if r["id"] == run_id:
            return {**r, "scorer_spans": scorer_spans(r["text"])}
    raise HTTPException(404, "No such run.")
