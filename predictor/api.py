"""HTTP API over the scoring engine, for the Angular front-end to consume.

Run:  uvicorn predictor.api:app --reload
Docs: http://127.0.0.1:8000/docs

Endpoints return the engine's structured output verbatim (counts, matched
phrases, bands, norming stats) so the front-end can render as much or as little
detail as it wants, and so later scoring-science work has everything exposed.
"""
from __future__ import annotations

import json
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .lta import TRAITS as LTA_TRAITS
from .vics import score_vics
from .score import analyze_with_bands, build_norm
from .mock_speeches import MOCK_SPEECHES
from . import llm
from . import stakeholders as stk
from . import auth
from . import dossier
from .extract import ExtractError, MAX_BYTES, extract_text
from .highlight import scorer_spans
from .speeches import split_speeches

app = FastAPI(title="PoliticalPredictor", version="0.1.0",
              summary="LTA + VICS at-a-distance speech scoring")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers on every response (OWASP A05 / XSS defense)."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return resp

# CORS: defaults to "*" for local dev; set ALLOWED_ORIGINS (comma-separated) in
# production to restrict to your frontend domain(s).
_origins_env = os.environ.get("ALLOWED_ORIGINS", "*").strip()
_allow_origins = ["*"] if _origins_env == "*" else [
    o.strip() for o in _origins_env.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
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


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    captcha_id: str = Field("", description="Self-hosted captcha challenge id")
    captcha_answer: str = Field("", description="The user's captcha answer")


class PasswordCheck(BaseModel):
    password: str = Field(..., min_length=1)


def _norm_for(corpus: list[str] | None):
    # None lets analyze_with_bands pick the default norm for the text's language.
    return build_norm(corpus) if corpus else None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/captcha")
def captcha() -> dict:
    """Issue a fresh self-hosted captcha challenge (public)."""
    return auth.new_captcha()


@app.post("/auth/login")
def login(req: LoginRequest, request: Request) -> dict:
    """Verify captcha + credentials, then issue a session token."""
    ip = request.client.host if request.client else "unknown"
    auth.rate_limit(ip)
    if not auth.check_captcha(req.captcha_id, req.captcha_answer):
        raise HTTPException(status_code=400, detail="captcha")
    if not auth.verify_password(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    auth.clear_attempts(ip)
    return {"token": auth.issue_token(req.username), "username": req.username}


@app.post("/auth/verify-password")
def verify_password(body: PasswordCheck, user: str = Depends(auth.require_auth)) -> dict:
    """Re-confirm the logged-in user's password (used to gate the PDF export)."""
    return {"ok": auth.verify_password(user, body.password)}


@app.get("/meta")
def meta(user: str = Depends(auth.require_auth)) -> dict:
    """Static metadata the UI can use to lay out results."""
    return {
        "lta_traits": list(LTA_TRAITS),
        "vics_indices": list(score_vics("placeholder text").keys()),
        "norming_corpus_default": list(MOCK_SPEECHES.keys()),
        "llm_available": llm.available(),
    }


@app.get("/mock-speeches")
def mock_speeches(user: str = Depends(auth.require_auth)) -> dict:
    """The labelled synthetic speeches (handy as front-end demo input)."""
    return MOCK_SPEECHES


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    norm = _norm_for(req.norming_corpus)
    # `spans`: where each counted word sits in the text, for highlighting.
    return {**analyze_with_bands(req.text, norm), "spans": scorer_spans(req.text)}


@app.post("/extract-text")
async def extract_text_endpoint(filename: str, request: Request,
                                user: str = Depends(auth.require_auth)) -> dict:
    """The speech text of an uploaded .txt, .pdf or .docx (the file is the raw body)."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="file-too-big")
    try:
        text = await run_in_threadpool(extract_text, filename, bytes(data))
    except ExtractError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return {"text": text, "speeches": split_speeches(text)}


@app.post("/split-speeches")
def split_speeches_endpoint(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    """The separate speakers in a pasted document (empty if there aren't several)."""
    return {"speeches": split_speeches(req.text)}


@app.post("/analyze/batch")
def analyze_batch(req: BatchRequest, user: str = Depends(auth.require_auth)) -> dict:
    norm = _norm_for(req.norming_corpus)
    return {"results": [analyze_with_bands(t, norm) for t in req.texts]}


@app.get("/stakeholders")
def stakeholders_list(user: str = Depends(auth.require_auth)) -> dict:
    """The stakeholder panel (built-in + user-added) the UI can render."""
    return {"stakeholders": stk.PROFILES_PUBLIC, "removed": stk.REMOVED_BUILTINS}


@app.get("/stakeholders/speeches")
def stakeholder_speeches(user: str = Depends(auth.require_auth)) -> dict:
    """Baseline speeches on disk, for the 'reuse an existing speech' picker."""
    return {"speeches": stk.list_speeches()}


@app.post("/stakeholders")
def add_stakeholder_endpoint(req: NewStakeholder, user: str = Depends(auth.require_auth)) -> dict:
    """Add a stakeholder; calibrate it if a baseline speech is provided."""
    try:
        return stk.add_stakeholder(req.model_dump(), language=req.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/stakeholders/{sid}")
def delete_stakeholder_endpoint(sid: str, user: str = Depends(auth.require_auth)) -> dict:
    """Remove a stakeholder from the panel."""
    if not stk.delete_stakeholder(sid):
        raise HTTPException(status_code=404, detail="No such stakeholder.")
    return {"deleted": sid}


@app.get("/stakeholders/{sid}/dossier")
def stakeholder_dossier(sid: str, language: str = "en",
                        user: str = Depends(auth.require_auth)) -> dict:
    """Profile of one stakeholder: compiled background, leadership style and alliances,
    plus recent coverage from trusted outlets in their country and abroad."""
    person = next((s for s in stk.STAKEHOLDERS if s["id"] == sid), None)
    if person is None:
        raise HTTPException(status_code=404, detail="No such stakeholder.")
    out = dossier.build(person, language="ar" if language == "ar" else "en")
    return {**out, "person": stk._public(person), "word_profile": stk.word_profile(sid)}


class NewSpeech(BaseModel):
    text: str
    title: str = ""


@app.post("/stakeholders/{sid}/speeches")
def add_stakeholder_speech(sid: str, req: NewSpeech, user: str = Depends(auth.require_auth)) -> dict:
    """Save one of this person's speeches; returns the updated word-scorer profile."""
    if not any(s["id"] == sid for s in stk.STAKEHOLDERS):
        raise HTTPException(status_code=404, detail="No such stakeholder.")
    try:
        return stk.add_speech(sid, req.text, req.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/stakeholders/{sid}/speeches/{speech_id}")
def delete_stakeholder_speech(sid: str, speech_id: str, user: str = Depends(auth.require_auth)) -> dict:
    """Remove a saved speech; returns the updated word-scorer profile."""
    if not stk.delete_speech(sid, speech_id):
        raise HTTPException(status_code=404, detail="No such saved speech.")
    return stk.word_profile(sid)


@app.get("/stakeholders/{sid}/mentions/{country}")
def stakeholder_mentions(sid: str, country: str, user: str = Depends(auth.require_auth)) -> dict:
    """What a built-in stakeholder said about one of their partner or rival countries."""
    prof = dossier.PROFILES.get(sid)
    listed = {dossier.country_of(l) for l in (prof["partners"] + prof["frictions"])} if prof else set()
    if country not in listed or sid not in dossier.ALIASES:
        raise HTTPException(status_code=404, detail="No such country in this profile.")
    return dossier.mentions(sid, country)


@app.post("/stakeholders/{sid}/restore")
def restore_stakeholder_endpoint(sid: str, user: str = Depends(auth.require_auth)) -> dict:
    """Put a removed built-in stakeholder back on the panel."""
    if not stk.restore_stakeholder(sid):
        raise HTTPException(status_code=404, detail="No such removed stakeholder.")
    return {"restored": sid}


@app.post("/analyze/stakeholders")
def analyze_stakeholders(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Predict how each stakeholder reacts to the speech / policy text."""
    return stk.react(req.text, language=req.language)


@app.post("/analyze/llm")
def analyze_llm(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Semantic LTA scoring via Groq (reads meaning, not keywords)."""
    try:
        return llm.score_llm(req.text, language=req.language)
    except llm.LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}")
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned malformed output: {exc}")
