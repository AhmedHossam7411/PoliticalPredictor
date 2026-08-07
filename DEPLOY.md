# Deploying PoliticalPredictor (free tier)

Three free services: **Neon** (Postgres), **Render** (FastAPI backend), **Vercel**
(Angular frontend). Everything deploys from your GitHub repo.

Prerequisite: push this repo to GitHub (Render and Vercel both deploy from it).

---

## 1. Database — Neon (Postgres)

**Option A — CLI (run in your own terminal; it needs a browser login):**
```bash
npx neonctl@latest init
```
It logs you in, creates a Neon project + database, and prints the **connection
string**. (It can't be run through the AI assistant — the login is interactive.)

**Option B — dashboard:** sign up at https://neon.tech, create a project, and
copy the connection string from the dashboard.

Either way you end up with a string like
`postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require`. Keep it for the
`DATABASE_URL` env var below — treat it as a **secret** (paste it into Render, not
into chat/commits). The `stakeholders` table is created automatically on first run.

> Test locally first (optional): `pip install "psycopg[binary]"`, set
> `DATABASE_URL` in your shell, run the backend, add a stakeholder, restart, and
> confirm it persisted.

## 2. Backend — free, no credit card (Hugging Face Spaces)

The repo has a `Dockerfile`, so the backend runs on any Docker host. Hugging Face
Spaces is genuinely free with **no card required**.

1. Sign up at https://huggingface.co (free).
2. **New → Space**. Name it, choose **Docker → Blank**, visibility Public.
3. In the Space's **Files**, add the backend. Easiest: add the Space as a git
   remote and push, or upload `Dockerfile`, `requirements.txt`, the `predictor/`
   folder, and `baseline_speeches/`.
4. In the Space **README.md** frontmatter, set `app_port: 7860`.
5. **Settings → Variables and secrets** → add secrets:
   - `GROQ_API_KEY` — your Groq key (AI scorer + calibration).
   - `DATABASE_URL` — the Neon string from step 1.
   - `ALLOWED_ORIGINS` — your Vercel URL (e.g. `https://political-predictor-jwrz.vercel.app`).
6. The Space builds and starts. Its public URL is like
   `https://<user>-<space>.hf.space`. Check `<url>/health` → `{"status":"ok"}`.

**Alternative (GitHub-native, still free, no card): Koyeb** — https://koyeb.com,
Create Service → GitHub → this repo → it detects the `Dockerfile` → set the same
three env vars → deploy. Koyeb injects `$PORT` automatically.

**Alternative (needs a card, but $0): Render** — New + → Blueprint reads
`render.yaml`; free web service, but Render requires a card on file.

> Free tiers sleep when idle, so the first request after a nap takes ~30–50s to
> wake. Hit the URL once before presenting to warm it up.

## 3. Frontend — Vercel (Angular)

1. In `frontend/src/index.html`, uncomment the API line and set it to your
   Render URL from step 2:
   ```html
   <script>window.__API_URL__ = 'https://politicalpredictor-api.onrender.com';</script>
   ```
   Commit and push.
2. Sign up at https://vercel.com, **Add New → Project**, import this repo.
3. Set **Root Directory** to `frontend`. Vercel reads `frontend/vercel.json`
   (build command + output dir are already configured).
4. Deploy. Copy the frontend URL, e.g. `https://politicalpredictor.vercel.app`.

## 4. Lock the two ends together

1. Back in Render, set `ALLOWED_ORIGINS` to your Vercel URL
   (e.g. `https://politicalpredictor.vercel.app`) and redeploy. This restricts
   the API to your frontend.
2. Open the Vercel URL, sign in (`admin` / `predict2026`), and add a stakeholder
   with a speech — it should persist across a backend restart (that confirms
   Postgres is wired up).

---

## Notes & Phase 2

- **Storage**: locally (no `DATABASE_URL`) the app uses JSON files; on Render
  (with `DATABASE_URL`) it uses Postgres. Same code, chosen at runtime.
- **Built-in stakeholders, profiles, and baseline speeches** ship in the repo
  (`predictor/baseline_profiles.json`, `baseline_speeches/`) — read-only, so
  they survive redeploys without a database.
- **Security (Phase 2)**: the login is still front-end only. Before real users,
  replace it with server-side accounts (hashed passwords + sessions), and add
  rate-limit/cost handling around the Groq calls.
