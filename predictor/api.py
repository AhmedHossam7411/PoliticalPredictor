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
from . import context as ctx
from . import entities
from . import labels_sync
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
    category: str | None = None  # organization / state / government / other; guessed if empty
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
    # `spans`: where each counted word sits in the text, for highlighting;
    # `entities`: where countries/organizations are named, and what is said of them.
    return {**analyze_with_bands(req.text, norm), "spans": scorer_spans(req.text),
            "entities": entities.find(req.text), "entity_summary": entities.summarize(req.text)}


# --- Context check ---------------------------------------------------------
class ContextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    decisions: dict | None = None
    norming_corpus: list[str] | None = None
    source: str = "person"


@app.post("/context/review")
def context_review(req: ContextRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Every sentence with a marked word or a named country/organization."""
    return ctx.review(req.text)


@app.post("/context/rescore")
def context_rescore(req: ContextRequest, user: str = Depends(auth.require_auth)) -> dict:
    """The word-scorer result again, with the context decisions applied."""
    out = ctx.rescore(req.text, req.decisions, _norm_for(req.norming_corpus))
    return {**out, "spans": scorer_spans(req.text), "entities": entities.find(req.text),
            "entity_summary": entities.summarize(req.text, ctx.tone_map(req.decisions))}


@app.post("/context/ai")
def context_ai_start(req: ContextRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Start Karnak's sentence-by-sentence context check; poll GET /context/ai/{job}."""
    # The saved examples go with it: reused for sentences decided before, shown to Karnak for the rest.
    # Examples that arrived with a `git pull` are read in first.
    labels_sync.pull_in(stk._store)
    return {"job": ctx.start_ai(req.text, stk._store.labels())}


@app.get("/context/ai/{job_id}")
def context_ai_status(job_id: str, user: str = Depends(auth.require_auth)) -> dict:
    job = ctx.job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    return job


@app.delete("/context/ai/{job_id}")
def context_ai_cancel(job_id: str, user: str = Depends(auth.require_auth)) -> dict:
    return {"cancelled": ctx.cancel(job_id)}


@app.post("/context/labels")
def context_save_labels(req: ContextRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Keep the reviewed sentences as labelled examples, for training a model later."""
    records = ctx.label_records(req.text, req.decisions or {}, req.source[:20])
    labels_sync.pull_in(stk._store)
    stk._store.save_labels(records)
    # Mirror to shared/context_labels.jsonl, which travels with the repository.
    total = labels_sync.export(stk._store)
    return {"saved": len(records), "total": total}


@app.get("/context/labels")
def context_labels(user: str = Depends(auth.require_auth)) -> dict:
    """Every labelled sentence saved so far (download for training)."""
    labels_sync.pull_in(stk._store)
    rows = stk._store.labels()
    return {"total": len(rows), "labels": rows, "sync": labels_sync.last_report}


# On start: take in examples that came with the repository, then make sure the shared
# file holds this computer's examples too (so they go out with the next push).
try:
    labels_sync.pull_in(stk._store, force=True)
    labels_sync.export(stk._store)
except Exception as _exc:  # never stop the server over the shared file
    print(f"[labels] could not sync shared/context_labels.jsonl: {_exc}")


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
def stakeholders_list(language: str = "en", user: str = Depends(auth.require_auth)) -> dict:
    """The stakeholder panel (built-in + user-added), in the interface language."""
    lang = "ar" if language == "ar" else "en"
    removed = stk.REMOVED_BUILTINS
    if lang == "ar":
        from .stakeholders_ar import AR
        removed = [{**r, "name": AR.get(r["id"], {}).get("name", r["name"])} for r in removed]
    return {"stakeholders": stk.public_list(lang), "removed": removed}


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
    lang = "ar" if language == "ar" else "en"
    out = dossier.build(person, language=lang)
    prof = dossier.in_arabic(sid, out["profile"]) if lang == "ar" else out["profile"]
    out = {**out, "profile": dossier.with_edits(sid, prof, stk.profile_edit(sid))}
    return {**out, "person": stk._public(stk.localized(person, lang)), "word_profile": stk.word_profile(sid),
            "entities": stk.entity_profile(sid)}


@app.get("/stakeholders/{sid}/entities/{key}")
def stakeholder_entity(sid: str, key: str, user: str = Depends(auth.require_auth)) -> dict:
    """Everything this person said about one country/organization in their speeches on file."""
    found = next((e for e in stk.entity_profile(sid) if e["key"] == key), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Not named in this person's speeches.")
    return found


class NewSpeech(BaseModel):
    text: str
    title: str = ""
    context: dict | None = None


@app.post("/stakeholders/{sid}/speeches")
def add_stakeholder_speech(sid: str, req: NewSpeech, user: str = Depends(auth.require_auth)) -> dict:
    """Save one of this person's speeches; returns the updated word-scorer profile."""
    if not any(s["id"] == sid for s in stk.STAKEHOLDERS):
        raise HTTPException(status_code=404, detail="No such stakeholder.")
    try:
        return stk.add_speech(sid, req.text, req.title, req.context)
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
    prof = {**(dossier.PROFILES.get(sid) or {}), **stk.profile_edit(sid)}
    listed = {dossier.country_of(l) for l in (prof.get("partners", []) + prof.get("frictions", []))}
    if country not in listed or sid not in dossier.ALIASES:
        raise HTTPException(status_code=404, detail="No such country in this profile.")
    return dossier.mentions(sid, country)


class EditStakeholder(BaseModel):
    name: str | None = None
    role: str | None = None
    category: str | None = None
    personality: str | None = None
    values: list[str] | None = None
    supports: list[str] | None = None
    opposes: list[str] | None = None
    concerns: list[str] | None = None
    profile: dict | None = None  # background, leadership_style, personality_type, memberships, partners, frictions


@app.put("/stakeholders/{sid}")
def edit_stakeholder(sid: str, req: EditStakeholder, user: str = Depends(auth.require_auth)) -> dict:
    """Change a stakeholder's details and profile; the original stays and can be restored."""
    try:
        return {"stakeholder": stk.edit_stakeholder(sid, req.model_dump(exclude_none=True))}
    except KeyError:
        raise HTTPException(status_code=404, detail="No such stakeholder.")


@app.delete("/stakeholders/{sid}/edits")
def reset_stakeholder(sid: str, user: str = Depends(auth.require_auth)) -> dict:
    """Undo every change made in this stakeholder's profile."""
    stk.reset_stakeholder(sid)
    return {"ok": True}


@app.post("/stakeholders/{sid}/restore")
def restore_stakeholder_endpoint(sid: str, user: str = Depends(auth.require_auth)) -> dict:
    """Put a removed built-in stakeholder back on the panel."""
    if not stk.restore_stakeholder(sid):
        raise HTTPException(status_code=404, detail="No such removed stakeholder.")
    return {"restored": sid}


@app.post("/analyze/stakeholders")
def analyze_stakeholders(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Predict how each stakeholder reacts to the speech / policy text, with what
    each of them thinks of the countries and organizations the text names."""
    out = stk.react(req.text, language=req.language)
    keys = [e["key"] for e in entities.summarize(req.text)]
    for r in out.get("reactions", []):
        r["views"] = stk.views_on(r["id"], keys, req.language) if keys else []
    return out


# --- Background jobs -------------------------------------------------------
# Karnak can take many minutes; run the AI steps on the server so a page refresh
# or another tab doesn't lose them. The page polls GET /jobs/{id}.
import threading as _threading
import time as _time
import uuid as _uuid

_JOBS: dict[str, dict] = {}


def _start_job(kind: str, fn, *args) -> str:
    job = {"id": _uuid.uuid4().hex[:12], "kind": kind, "status": "running",
           "started": _time.time(), "result": None, "error": "", "code": 0}
    for old in sorted(_JOBS, key=lambda k: _JOBS[k]["started"])[:-20]:
        _JOBS.pop(old, None)
    _JOBS[job["id"]] = job

    def run():
        try:
            job["result"] = fn(*args)
            job["status"] = "done"
        except HTTPException as exc:
            job.update(status="failed", error=str(exc.detail), code=exc.status_code)
        except Exception as exc:  # keep the server up; report what went wrong
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300], code=500)
    _threading.Thread(target=run, daemon=True).start()
    return job["id"]


@app.post("/jobs/llm")
def job_llm(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    return {"job": _start_job("llm", analyze_llm, req, user)}


@app.post("/jobs/stakeholders")
def job_stakeholders(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    return {"job": _start_job("stakeholders", analyze_stakeholders, req, user)}


@app.get("/jobs/{job_id}")
def job_status(job_id: str, user: str = Depends(auth.require_auth)) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job (the server may have restarted).")
    return job


@app.post("/analyze/llm")
def analyze_llm(req: AnalyzeRequest, user: str = Depends(auth.require_auth)) -> dict:
    """Semantic LTA scoring by the local AI (reads meaning, not keywords)."""
    try:
        return llm.score_llm(req.text, language=req.language)
    except llm.LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=llm.not_running_reason())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}")
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned malformed output: {exc}")
