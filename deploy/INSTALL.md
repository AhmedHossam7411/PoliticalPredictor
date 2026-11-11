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
| AI on this machine, with NVIDIA GPU (16 GB+ video memory) | 4 cores, 16 GB RAM | 30 GB |
| AI on this machine, CPU only | 4 cores, 16 GB RAM | 20 GB |

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

## 3. The AI (Karnak-6B, on this machine)

The dictionary scoring (LTA and VICS) always runs inside the `api`
container. Separately, an AI reads each speech for trait scores and
stakeholder reactions. That AI is **Karnak-6B** (Applied Innovation Center,
Egypt; Apache 2.0), running in the `ollama` container on this machine.
**No speech text leaves the machine.**

`.env.example` already has the settings:

```
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=hf.co/mradermacher/Karnak-6B-v1.0-GGUF:Q4_K_M
LLM_TIMEOUT=3600
```

Start with the `local-ai` profile (section 5). Then download the model
once, about 3.7 GB:

```bash
docker compose --profile local-ai exec ollama ollama pull hf.co/mradermacher/Karnak-6B-v1.0-GGUF:Q4_K_M
```

With an NVIDIA GPU, install the NVIDIA Container Toolkit
(<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/>) and
add the GPU file to every command:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile local-ai up -d --build
```

Karnak-6B runs on an ordinary computer without a graphics card, but
slowly: an analysis can take 10 minutes or more. Its trait scores are
good; its stakeholder reactions are weaker than a large model's.

### Another server instead

To use a different OpenAI-compatible server (for example an in-house vLLM
running a larger model), point the settings at it:

```
LLM_BASE_URL=https://your-server/v1
LLM_API_KEY=...
LLM_MODEL=<model name on that server>
```

The server must support JSON output (`response_format: json_object`).

### AI not running

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
docker compose --profile local-ai up -d --build  # Karnak on this machine
docker compose up -d --build                     # only with "Another server instead"
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

Run all commands from the `deploy` folder. Add `--profile local-ai` unless
you use "Another server instead".

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

You also need the Karnak model, which `ollama pull` can't download
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
| Stakeholders show "Fallback" with "not running" or "ConnectError" | The `ollama` container is not running or the model is not downloaded: start with `--profile local-ai` and run the `ollama pull` in section 3. |
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
