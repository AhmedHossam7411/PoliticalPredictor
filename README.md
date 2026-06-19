# PoliticalPredictor

At-a-distance political leadership profiling. Scores a leader's speech/interview on:

- **LTA** — Hermann's Leadership Trait Analysis (7 traits)
- **VICS** — Walker's operational-code indices
- **LLM (Groq)** — a semantic scorer that reads *meaning*, not keywords

Two scorers run side by side: the dictionary scorer is fast, free, and
explainable; the Groq LLM scorer handles natural prose where meaning ≠ vocabulary.

## Architecture

```
predictor/        Python scoring engine + FastAPI  (see predictor/README.md)
frontend/         Angular app that calls the API
```

## Run it

**1. Backend** (Python 3.11+):
```bash
pip install -r requirements.txt
# Groq LLM scorer (optional but recommended):
setx GROQ_API_KEY "your-key"          # Windows; or export on macOS/Linux
uvicorn predictor.api:app --reload     # http://127.0.0.1:8000  (docs at /docs)
```

**2. Frontend** (Node 20+):
```bash
cd frontend
npm install
npx ng serve                           # http://localhost:4200
```

Open http://localhost:4200, paste a speech (or pick a sample), and hit
**Analyze — Dictionary** and/or **Analyze — LLM (Groq)**.

## Status

- Engine, both scorers, and API: working and live-tested.
- LLM scorer matches the labelled mock profiles closely on natural prose where
  the dictionary scorer under-signals (see `predictor/README.md` for the analysis).
- The dictionary LTA bands are **relative** to a norming corpus (default: the
  bundled mock speeches).

## Notes for deployment
- CORS is open (`*`) for dev — restrict `allow_origins` to the Angular origin.
- Keep `GROQ_API_KEY` server-side only (the front-end never sees it).
