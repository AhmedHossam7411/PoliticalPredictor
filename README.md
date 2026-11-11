# PoliticalPredictor

At-a-distance political leadership profiling. Scores a leader's speech/interview on:

- **LTA** — Hermann's Leadership Trait Analysis (7 traits)
- **VICS** — Walker's operational-code indices
- **AI (Karnak-6B)** — a semantic scorer that reads *meaning*, not keywords

Two scorers run side by side: the dictionary scorer is fast, free, and
explainable; the AI scorer handles natural prose where meaning ≠ vocabulary.
The AI is Karnak-6B (Applied Innovation Center, Egypt; Apache 2.0) running on
the same computer, so no speech text is sent anywhere.

## Architecture

```
predictor/        Python scoring engine + FastAPI  (see predictor/README.md)
frontend/         Angular app that calls the API
```

## Run it

Three terminal windows, started in this order.

**1. The AI** (one-time: install llama.cpp, e.g. `brew install llama.cpp` on a
Mac or the zip from <https://github.com/ggml-org/llama.cpp/releases> on
Windows, and download the 3.7 GB model
<https://huggingface.co/mradermacher/Karnak-6B-v1.0-GGUF/resolve/main/Karnak-6B-v1.0.Q4_K_M.gguf>):
```bash
llama-server -m Karnak-6B-v1.0.Q4_K_M.gguf -c 16384 --port 8080 --alias karnak-6b
```

**2. Backend** (Python 3.11–3.12):
```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn predictor.api:app --port 8000   # http://127.0.0.1:8000  (docs at /docs)
```
It finds Karnak at `http://127.0.0.1:8080` by itself; no key or settings needed.

**3. Frontend** (Node 20.19+):
```bash
cd frontend
npm install
npx ng serve --port 4200               # http://localhost:4200
```

Open http://localhost:4200, log in (`admin` / `predict2026` by default), paste
a speech (or pick a sample), and analyze. On an ordinary computer the AI part
takes several minutes; the dictionary results come back at once.

## Arabic input

Paste Arabic text — Modern Standard (فصحى) or Egyptian colloquial (عامية مصرية) — and
it is scored like English. The detected language/dialect is shown above your text.

- **Dictionary scorer:** Arabic LTA word lists in `predictor/lexicons/lta_ar/`, matched
  with clitic-aware rules (`predictor/arabic.py`: و/ف/ب/ل/ال، Egyptian هـ/حـ future,
  pronoun suffixes…). Bands are normed against Arabic samples, not English ones.
  VICS is English-only and is skipped for Arabic.
- **LLM scorer + stakeholders:** told the language and dialect, and scored on the
  same scale as English.
- **Samples:** `sample_speeches_ar/` has each labelled mock speech in Fusha (`_msa`)
  and Egyptian (`_egy`). Check ordering against their labels with
  `python -m predictor.score`.
- The Arabic word lists are a first draft — have an Arabic-speaking analyst review them.

## Status

- Engine, both scorers, and API: working and live-tested.
- LLM scorer matches the labelled mock profiles closely on natural prose where
  the dictionary scorer under-signals (see `predictor/README.md` for the analysis).
- The dictionary LTA bands are **relative** to a norming corpus (default: the
  bundled mock speeches).

## Notes for deployment
- CORS is open (`*`) for dev — restrict `allow_origins` to the Angular origin.
- The AI runs on the same machine; no API key is needed or stored.

## Handing the system to another organization
`deploy/` is a self-contained kit: app, API, Postgres and the Karnak AI model
(Ollama), started with one `docker compose` command. They run it on
their own machine; [deploy/INSTALL.md](deploy/INSTALL.md) is the guide to give
them. Commit, then `bash deploy/make-bundle.sh` (add `--with-images` for an
offline server) writes the bundle to `deploy/dist/`.

The AI server is configurable (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`,
`LLM_TIMEOUT`; local Karnak is the default), for example to point at a larger
in-house model.
