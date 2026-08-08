"""Authentication + baseline API security.

- Credentials: verified constant-time against AUTH_USERNAME / AUTH_PASSWORD, or a
  PBKDF2 hash in AUTH_PASSWORD_HASH (preferred for production — never store the
  plaintext password there).
- Sessions: short-lived signed JWT (HS256) using SESSION_SECRET.
- reCAPTCHA v2: the token is verified with Google before login can succeed.
  Defaults to Google's official TEST keys so local dev works out of the box;
  set RECAPTCHA_SECRET (and the frontend site key) for production.
- Brute force: in-memory per-IP rate limit on the login endpoint.

Generate a production password hash:
    python -c "from predictor.auth import hash_password; print(hash_password('yourpw'))"
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# --- Config (env-overridable; dev-friendly defaults) ------------------------
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "predict2026")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "")  # pbkdf2_sha256$...

SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-change-me")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "28800"))  # 8 hours

# Google's official reCAPTCHA v2 TEST secret — always verifies successfully.
# Override with your real secret in production (frontend uses the matching site key).
RECAPTCHA_SECRET = os.environ.get(
    "RECAPTCHA_SECRET", "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe")
_RECAPTCHA_URL = "https://www.google.com/recaptcha/api/siteverify"

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


# --- reCAPTCHA v2 -----------------------------------------------------------
def verify_captcha(token: str, remote_ip: str | None = None) -> bool:
    if not token:
        return False
    data = {"secret": RECAPTCHA_SECRET, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        resp = httpx.post(_RECAPTCHA_URL, data=data, timeout=10)
        resp.raise_for_status()
        return bool(resp.json().get("success"))
    except httpx.HTTPError:
        return False


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
