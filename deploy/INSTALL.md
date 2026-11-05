# PoliticalPredictor: installation guide

This guide sets up the complete system on a machine you control. It is written
for the IT person doing the install. No knowledge of the code is needed.

## What gets installed

Four containers run together, started by one command:

| Container | What it does |
|-----------|--------------|
| `web`     | The web app users open in a browser. Also forwards requests to `api`. |
| `api`     | The analysis engine: LTA and VICS dictionary scoring, AI trait scoring, stakeholder reactions, login. |
| `db`      | PostgreSQL database for stakeholders you add. |
| `ollama`  | Optional. Runs the AI model on this machine instead of a cloud service. |

Users only ever connect to `web`, on one port (8080 by default). The other
containers are not reachable from the network.

## 1. Requirements

**Machine:** a Linux server (Ubuntu 22.04+ recommended), or a Windows/Mac PC
running Docker Desktop.

| Setup | CPU / RAM | Disk |
|-------|-----------|------|
| Cloud AI (option A or C below) | 2 cores, 4 GB RAM | 10 GB |
| AI on this machine, with NVIDIA GPU (16 GB+ video memory) | 4 cores, 16 GB RAM | 30 GB |
| AI on this machine, CPU only | 8 cores, 32 GB RAM | 30 GB |

CPU only works but is slow: an analysis can take several minutes.

**Software:** Docker Engine 24+ with the Compose plugin.
- Ubuntu: follow <https://docs.docker.com/engine/install/ubuntu/>.
- Windows: Docker Desktop also needs virtualization switched on in the BIOS
  and the Windows "Virtual Machine Platform" feature
  (`wsl --install --no-distribution` as administrator, then reboot).

Check it works: `docker compose version`.

## 2. Unpack and configure

```bash
unzip politicalpredictor-<version>.zip
cd politicalpredictor-<version>/deploy
cp .env.example .env
```

Open `.env` in a text editor and fill in the values below. You can generate
random values with `openssl rand -hex 32`, or with
`python3 -c "import secrets; print(secrets.token_hex(32))"`.

| Setting | What to put |
|---------|-------------|
| `SESSION_SECRET` | A random value of 32+ characters. |
| `POSTGRES_PASSWORD` | A random value, letters and digits only. |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | The login for the app. Section 4 covers storing a hash instead. |
| AI settings | See section 3. |

The app **refuses to start** while the login or `SESSION_SECRET` is missing,
or still set to a built-in default. That's deliberate.

Keep `.env` private: it holds every secret of the installation.

## 3. Choose the AI

The dictionary scoring (LTA and VICS) always runs inside the `api`
container. Separately, the AI reads each speech for trait scores and
stakeholder reactions. Pick where that AI runs:

### Option A: Groq cloud (simplest)

Create an API key at <https://console.groq.com> and set:

```
GROQ_API_KEY=gsk_...
```

**Data note:** the full speech text is sent to Groq, a US company. The free
tier allows about 8,000 tokens per minute. That is enough for one user at a
time. When it runs out, the app waits or switches to a fallback model. For
several users, use Groq's paid Developer tier.

### Option B: AI on this machine (no data leaves it)

Uses Ollama with OpenAI's open-weight `gpt-oss` model. In `.env`, remove
`GROQ_API_KEY` and set:

```
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=gpt-oss:20b
LLM_TIMEOUT=300
```

Start with the `local-ai` profile (section 5). Then download the model
once, about 14 GB:

```bash
docker compose --profile local-ai exec ollama ollama pull gpt-oss:20b
```

With an NVIDIA GPU, install the NVIDIA Container Toolkit
(<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/>) and
add the GPU file to every command:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile local-ai up -d --build
```

`gpt-oss:120b` gives the best results (the system was validated on it), but
it needs a GPU with about 80 GB of memory. `gpt-oss:20b` is the practical
choice for a single GPU.

### Option C: another OpenAI-compatible server

For example vLLM, an existing in-house model gateway, or Azure OpenAI:

```
LLM_BASE_URL=https://your-server/v1
LLM_API_KEY=...
LLM_MODEL=<model name on that server>
```

The server must support JSON output (`response_format: json_object`).

### No AI configured

The app still works. Dictionary scores are complete. Stakeholder reactions
fall back to a basic keyword method, and the app says so on screen. That
keyword method works for English text only.

## 4. Set the login

The simplest setup is a plain `AUTH_PASSWORD` in `.env`. Preferably, store
only a hash of the password: after setting `SESSION_SECRET` and
`POSTGRES_PASSWORD`, run:

```bash
docker compose run --rm --no-deps -e REQUIRE_SECRETS=0 api \
  python -c "from predictor.auth import hash_password; print(hash_password('YOUR-PASSWORD'))"
```

Put the output in `.env` **inside single quotes**, because it contains `$`
characters. Then empty `AUTH_PASSWORD`:

```
AUTH_PASSWORD=
AUTH_PASSWORD_HASH='pbkdf2_sha256$200000$...'
```

The system has one login, shared by everyone who uses it.

## 5. Start

```bash
docker compose up -d --build                     # options A / C
docker compose --profile local-ai up -d --build  # option B
```

The first build takes 5–10 minutes. Check that everything is up:

```bash
docker compose ps          # api should show "healthy"
docker compose logs api    # look for errors
```

Open `http://<this-machine>:8080` in a browser and log in.

To test it, paste a speech and press Analyze. You should get trait bands
(dictionary), AI trait scores, and eight stakeholder reactions. The summary
says "AI analysis" when the AI answered, or "Fallback" when it didn't.

## 6. Access from other computers

Any computer on the same network can use `http://<server-ip>:8080`. Allow
the port through the server's firewall, for example on Ubuntu with
`sudo ufw allow 8080/tcp`. To change the port, set `WEB_PORT` in `.env`.

The app serves **plain HTTP**. That is fine on a trusted internal network. If
users reach it across the internet or an untrusted network, put it behind
your existing HTTPS reverse proxy or load balancer, pointed at port 8080.
Don't expose port 8080 directly to the internet.

## 7. Day-to-day operation

Run all commands from the `deploy` folder. Add `--profile local-ai` if you
use option B.

| Task | Command |
|------|---------|
| Stop | `docker compose down` (data is kept) |
| Start | `docker compose up -d` |
| Logs | `docker compose logs -f api` |
| Apply a `.env` change | `docker compose up -d` |

**Back up** the database, which holds the stakeholders you add:

```bash
docker compose exec -T db pg_dump -U predictor predictor > backup-$(date +%F).sql
```

**Restore** (into a fresh installation, before adding any stakeholders):

```bash
docker compose exec -T db psql -U predictor predictor < backup-2026-01-31.sql
```

Also keep a copy of `.env` somewhere safe.

**Update to a new version:** unpack the new bundle and copy your `.env` into
its `deploy` folder. Then run `docker compose up -d --build` there. The
database lives in a Docker volume, so it carries over.

**Remove everything, including data:** `docker compose down -v`.

## 8. Offline install (no internet on the server)

The supplier provides a second file, `politicalpredictor-<version>-images.tar`,
containing all four images, already built. On the server:

```bash
docker load -i politicalpredictor-<version>-images.tar
```

Put `VERSION=<version>` in `.env`, using the version from the file name.
Then start with `docker compose up -d`, **without** `--build`.

For option B, you also need the model, which `ollama pull` can't download
offline. On a machine with internet, pull it, then copy the volume across:

```bash
docker run --rm -v politicalpredictor_ollama:/data -v "$PWD":/out alpine tar czf /out/ollama-models.tgz -C /data .
# on the server, before starting:
docker volume create politicalpredictor_ollama
docker run --rm -v politicalpredictor_ollama:/data -v "$PWD":/in alpine tar xzf /in/ollama-models.tgz -C /data
```

## 9. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `api` keeps restarting; log says `REQUIRE_SECRETS=1 but ...` | Fill in the settings it names in `.env`. |
| `set POSTGRES_PASSWORD in .env` | `POSTGRES_PASSWORD` is empty. |
| "Cannot reach the analyzer" | `api` is not running or still starting: check `docker compose ps` and `docker compose logs api`. |
| Stakeholders show "Fallback" with "rate limit reached (HTTP 429)" | Groq free-tier limit. Wait a minute, use a paid tier, or option B. |
| Stakeholders show "Fallback" with a timeout | The local model is too slow. Raise `LLM_TIMEOUT`, add a GPU, or use a smaller model. |
| Login says "Too many attempts" | `LOGIN_MAX_ATTEMPTS` failures from that computer. Wait `LOGIN_WINDOW_SECONDS` (default 5 minutes). |
| Changed `POSTGRES_PASSWORD` after first start, now `api` can't connect | The database keeps its original password. Put the old one back, or reset the data with `docker compose down -v`. |

## 10. What the system measures, and its limits

- **LTA (Hermann's Leadership Trait Analysis):** seven traits, scored two ways:
  - word lists, in English, Modern Standard Arabic and Egyptian Arabic
  - AI reading
- **VICS (Walker's Verbs in Context):** operational-code beliefs, from word
  lists. **English only**; it is skipped for Arabic text.
- **Stakeholder reactions:** the AI predicts how each panel member would
  respond. Eight members and their profiles come with the system; users can
  add their own.
- Dictionary bands are relative to a built-in reference set of speeches,
  separate for English and Arabic. Short texts give unstable bands.
- Word lists can't detect negation ("we will **not** attack" still counts
  "attack").
- AI scores can vary slightly between runs and between models.
- The Arabic word lists are a reviewed draft. Have a specialist review them
  before relying on Arabic results.

These are research instruments for at-a-distance profiling. They are not a
substitute for expert judgment.
