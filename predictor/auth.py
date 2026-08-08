"""Authentication + baseline API security.

- Credentials: verified constant-time against AUTH_USERNAME / AUTH_PASSWORD, or a
  PBKDF2 hash in AUTH_PASSWORD_HASH (preferred for production — never store the
  plaintext password there).
- Sessions: short-lived signed JWT (HS256) using SESSION_SECRET.
- CAPTCHA: a self-hosted distorted-text challenge (SVG) — the answer is kept
  server-side and consumed on use. No external service or signup required.
- Brute force: in-memory per-IP rate limit on the login endpoint.

Generate a production password hash:
    python -c "from predictor.auth import hash_password; print(hash_password('yourpw'))"
"""
from __future__ import annotations

import hashlib
import hmac
import os
import random
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# --- Config (env-overridable; dev-friendly defaults) ------------------------
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "predict2026")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "")  # pbkdf2_sha256$...

SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-change-me")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "28800"))  # 8 hours

_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "8"))
_WINDOW = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))  # 5 minutes


# --- Password hashing (stdlib PBKDF2, no native deps) -----------------------
def _pbkdf2(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()


def hash_password(password: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${_pbkdf2(password, salt, iterations)}"


def _verify_hash(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = _pbkdf2(password, bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(calc, hash_hex)
    except (ValueError, TypeError):
        return False


def verify_password(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username or "", AUTH_USERNAME)
    if AUTH_PASSWORD_HASH:
        pass_ok = _verify_hash(password or "", AUTH_PASSWORD_HASH)
    else:
        pass_ok = hmac.compare_digest(password or "", AUTH_PASSWORD)
    return user_ok and pass_ok


# --- JWT sessions -----------------------------------------------------------
def issue_token(username: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": username, "iat": now, "exp": now + TOKEN_TTL_SECONDS},
        SESSION_SECRET, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)


def require_auth(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """FastAPI dependency: 401 unless a valid session token is presented."""
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        payload = jwt.decode(cred.credentials, SESSION_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return str(payload.get("sub", ""))


# --- Self-hosted CAPTCHA (no external service) ------------------------------
# Distorted-text challenge rendered as SVG; the answer is kept server-side and
# consumed on use. Ambiguous characters are excluded.
_CAPTCHA_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CAPTCHA_TTL = 300  # seconds
_CAPTCHAS: dict[str, tuple[str, float]] = {}


def _captcha_svg(code: str) -> str:
    w, h = 170, 60
    parts = [f'<rect width="{w}" height="{h}" fill="#eef2f8"/>']
    for _ in range(5):  # noise lines
        parts.append(
            f'<line x1="{random.randint(0, w)}" y1="{random.randint(0, h)}" '
            f'x2="{random.randint(0, w)}" y2="{random.randint(0, h)}" '
            f'stroke="#94a3b8" stroke-width="1" opacity="0.5"/>')
    x = 20
    palette = ["#1d4ed8", "#0e7490", "#7c3aed", "#b45309", "#15803d"]
    for ch in code:
        rot = random.randint(-28, 28)
        y = random.randint(36, 44)
        parts.append(
            f'<text x="{x}" y="{y}" font-size="32" font-family="monospace" '
            f'font-weight="700" fill="{random.choice(palette)}" '
            f'transform="rotate({rot} {x} {y})">{ch}</text>')
        x += 28
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="captcha">'
            + "".join(parts) + "</svg>")


def new_captcha() -> dict:
    """Create a challenge; returns its id + inline SVG for the login form."""
    now = time.time()
    for k, (_, exp) in list(_CAPTCHAS.items()):  # opportunistic cleanup
        if exp < now:
            _CAPTCHAS.pop(k, None)
    code = "".join(random.choice(_CAPTCHA_CHARS) for _ in range(5))
    cid = secrets.token_urlsafe(16)
    _CAPTCHAS[cid] = (code, now + _CAPTCHA_TTL)
    return {"id": cid, "svg": _captcha_svg(code)}


def check_captcha(captcha_id: str, answer: str) -> bool:
    entry = _CAPTCHAS.pop(captcha_id or "", None)  # single-use
    if not entry:
        return False
    code, exp = entry
    if time.time() > exp:
        return False
    return (answer or "").strip().upper() == code


# --- Login brute-force rate limit (in-memory, per IP) -----------------------
_ATTEMPTS: dict[str, list[float]] = {}


def rate_limit(ip: str) -> None:
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(ip, []) if now - t < _WINDOW]
    if len(hits) >= _MAX_ATTEMPTS:
        raise HTTPException(status_code=429,
                            detail="Too many attempts. Please wait and try again.")
    hits.append(now)
    _ATTEMPTS[ip] = hits


def clear_attempts(ip: str) -> None:
    _ATTEMPTS.pop(ip, None)
