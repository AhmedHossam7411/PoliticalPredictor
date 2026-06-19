"""HTTP API over the scoring engine, for the Angular front-end to consume.

Run:  uvicorn predictor.api:app --reload
Docs: http://127.0.0.1:8000/docs

Endpoints return the engine's structured output verbatim (counts, matched
phrases, bands, norming stats) so the front-end can render as much or as little
detail as it wants, and so later scoring-science work has everything exposed.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .lta import TRAITS as LTA_TRAITS
from .vics import score_vics
from .score import analyze_with_bands, build_norm, default_norm
from .mock_speeches import MOCK_SPEECHES

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


class BatchRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    norming_corpus: list[str] | None = None


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
