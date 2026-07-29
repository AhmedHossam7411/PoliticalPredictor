"""HTTP API over the scoring engine, for the Angular front-end to consume.

Run:  uvicorn predictor.api:app --reload
Docs: http://127.0.0.1:8000/docs

Endpoints return the engine's structured output verbatim (counts, matched
phrases, bands, norming stats) so the front-end can render as much or as little
detail as it wants, and so later scoring-science work has everything exposed.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .lta import TRAITS as LTA_TRAITS
from .vics import score_vics
from .score import analyze_with_bands, build_norm, default_norm
from .mock_speeches import MOCK_SPEECHES
from . import llm
from . import stakeholders as stk

app = FastAPI(title="PoliticalPredictor", version="0.1.0",
              summary="LTA + VICS at-a-distance speech scoring")

# Allow the Angular dev server (and others) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to the Angular origin before deploy
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Speech / interview text")
    norming_corpus: list[str] | None = Field(
        None, description="Optional texts to norm LTA bands against; "
                          "defaults to the bundled mock-speech corpus.")
    language: str = Field("en", description="Language for LLM prose output (e.g. en, ar)")


class BatchRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    norming_corpus: list[str] | None = None


class NewStakeholder(BaseModel):
    name: str = Field(..., min_length=1)
    role: str = ""
    scope: str = ""
    personality: str = ""
    values: list[str] = []
    supports: list[str] = []
    opposes: list[str] = []
    concerns: list[str] = []
    responses: list[str] = []
    speech_text: str | None = Field(None, description="Paste a new baseline speech")
    speech_from: str | None = Field(None, description="Reuse an existing baseline speech id")
    language: str = "en"


def _norm_for(corpus: list[str] | None):
    return build_norm(corpus) if corpus else default_norm()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict:
    """Static metadata the UI can use to lay out results."""
    return {
        "lta_traits": list(LTA_TRAITS),
        "vics_indices": list(score_vics("placeholder text").keys()),
        "norming_corpus_default": list(MOCK_SPEECHES.keys()),
        "llm_available": llm.available(),
    }


@app.get("/mock-speeches")
def mock_speeches() -> dict:
    """The labelled synthetic speeches (handy as front-end demo input)."""
    return MOCK_SPEECHES


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest) -> dict:
    norm = _norm_for(req.norming_corpus)
    return analyze_with_bands(req.text, norm)


@app.post("/analyze/batch")
def analyze_batch(req: BatchRequest) -> dict:
    norm = _norm_for(req.norming_corpus)
    return {"results": [analyze_with_bands(t, norm) for t in req.texts]}


@app.get("/stakeholders")
def stakeholders_list() -> dict:
    """The stakeholder panel (built-in + user-added) the UI can render."""
    return {"stakeholders": stk.PROFILES_PUBLIC}


@app.get("/stakeholders/speeches")
def stakeholder_speeches() -> dict:
    """Baseline speeches on disk, for the 'reuse an existing speech' picker."""
    return {"speeches": stk.list_speeches()}


@app.post("/stakeholders")
def add_stakeholder_endpoint(req: NewStakeholder) -> dict:
    """Add a stakeholder; calibrate it if a baseline speech is provided."""
    try:
        return stk.add_stakeholder(req.model_dump(), language=req.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/stakeholders/{sid}")
def delete_stakeholder_endpoint(sid: str) -> dict:
    """Remove a user-added stakeholder (built-ins cannot be deleted)."""
    if not stk.delete_stakeholder(sid):
        raise HTTPException(status_code=404, detail="No such custom stakeholder.")
    return {"deleted": sid}


@app.post("/analyze/stakeholders")
def analyze_stakeholders(req: AnalyzeRequest) -> dict:
    """Predict how each stakeholder reacts to the speech / policy text."""
    return stk.react(req.text, language=req.language)


@app.post("/analyze/llm")
def analyze_llm(req: AnalyzeRequest) -> dict:
    """Semantic LTA scoring via Groq (reads meaning, not keywords)."""
    try:
        return llm.score_llm(req.text, language=req.language)
    except llm.LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}")
