# Security

How PoliticalPredictor addresses the OWASP Top 10 (2021).

## Authentication
- Login is **server-side** (`POST /auth/login`). The browser no longer holds any
  password.
- Credentials are checked **constant-time** (`hmac.compare_digest`). Production
  stores a **PBKDF2-SHA256 hash** in `AUTH_PASSWORD_HASH` (never the plaintext):
  ```
  python -c "from predictor.auth import hash_password; print(hash_password('yourpw'))"
  ```
- On success the server issues a short-lived **JWT** (HS256, signed with
  `SESSION_SECRET`, 8-hour expiry). The frontend stores it in `sessionStorage`
  and sends it as `Authorization: Bearer …`.
- **reCAPTCHA v2** is verified with Google before login can succeed (bot/brute
  defense). Dev uses Google's official test keys; set `RECAPTCHA_SECRET` +
  the frontend site key for production.

## OWASP Top 10 mapping
| # | Risk | Mitigation |
|---|------|------------|
| A01 | Broken Access Control | Every functional endpoint requires a valid JWT via the `require_auth` dependency; only `/health` and `/auth/login` are public. |
| A02 | Cryptographic Failures | Passwords hashed (PBKDF2); sessions are signed JWTs; secrets come from env, never committed. |
| A03 | **Injection (SQLi)** | Postgres access is 100% **parameterized** (`psycopg` `%s` placeholders in `store.py`); no string-built SQL. The JSON store has no SQL surface. |
| A03 | **Injection (XSS)** | Angular auto-escapes all template bindings; the app uses no `innerHTML`/`bypassSecurityTrust`; the PDF HTML is built with an explicit `esc()` escaper. Security headers add defense-in-depth. |
| A04 | Insecure Design | reCAPTCHA + rate limiting on login; least-privilege endpoints. |
| A05 | Security Misconfiguration | Security headers on API responses (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Content-Security-Policy`) and on the Vercel frontend (`vercel.json`); CORS restricted to `ALLOWED_ORIGINS` in production. |
| A06 | Vulnerable Components | Minimal, pinned dependencies; pure-Python auth libs (no native build). |
| A07 | Identification & Auth Failures | Constant-time credential check, captcha, brute-force rate limit (`LOGIN_MAX_ATTEMPTS` per `LOGIN_WINDOW_SECONDS` per IP), expiring tokens. |
| A08 | Data Integrity | JWTs are signed and verified; reCAPTCHA tokens verified server-side. |
| A09 | Logging & Monitoring | (Roadmap) add structured auth-event logging for Contabo. |
| A10 | SSRF | No user-controlled outbound URLs; the only outbound calls are to fixed Groq and Google reCAPTCHA endpoints. |

## Environment variables (production)
| Var | Purpose |
|-----|---------|
| `AUTH_USERNAME` | admin username |
| `AUTH_PASSWORD_HASH` | PBKDF2 hash of the password (use instead of `AUTH_PASSWORD`) |
| `SESSION_SECRET` | strong random string that signs JWTs (**must** be set) |
| `RECAPTCHA_SECRET` | your real reCAPTCHA v2 secret |
| `ALLOWED_ORIGINS` | comma-separated frontend origin(s) for CORS |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS` | brute-force limits (optional) |

Frontend: set the real reCAPTCHA **site key** in `frontend/src/app/app.html`
(`data-sitekey`) and point `window.__API_URL__` at the backend.

## Known limitations / roadmap
- reCAPTCHA + JWT are single-tenant (one admin). Multi-tenant accounts come with
  the Contabo migration.
- Rate limiting is in-memory (fine for a single instance); use a shared store if
  scaled horizontally.
- Finalize a strict frontend Content-Security-Policy once the backend domain is
  fixed (needs `connect-src` = backend, `script-src`/`frame-src` = Google reCAPTCHA).
