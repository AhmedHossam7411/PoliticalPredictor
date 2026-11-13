"""AI scorer for LTA traits -- the semantic complement to the dictionary.

The dictionary scorer only sees vocabulary; this reads *meaning*, so it rates a
speech that is "high power" in tone even when it uses no literal power words.
Returns the same seven traits on a 0-100 scale plus a short rationale each.

The AI is Karnak-6B running on this computer (llama.cpp's llama-server on port
8080), so speech text never leaves the machine. Any other OpenAI-compatible
server can be used instead by setting LLM_BASE_URL, LLM_MODEL and, if that
server needs one, LLM_API_KEY.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time

import httpx

from . import arabic

LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
BASE_URL = (os.environ.get("LLM_BASE_URL") or LOCAL_BASE_URL).rstrip("/")
CHAT_URL = BASE_URL + "/chat/completions"
DEFAULT_MODEL = "karnak-6b"
# A model on an ordinary computer is slow: allow up to 5 hours per call.
TIMEOUT = float(os.environ.get("LLM_TIMEOUT") or 18000)
# Most input tokens to send in one call. Karnak is started with a 16k context,
# which leaves room for the prompt and the answer.
MAX_INPUT_TOKENS = int(os.environ.get("LLM_MAX_INPUT_TOKENS") or 7500)
# Karnak is started with -np 1: it works on one request at a time and queues the
# rest. Waiting in its queue counted against TIMEOUT, so a request stuck behind
# the context check and the traits ran out of time before Karnak even began it.
# Calls now wait their turn here, and the timeout covers only Karnak's own work.
PARALLEL = max(1, int(os.environ.get("LLM_PARALLEL") or 1))
_TURN = threading.BoundedSemaphore(PARALLEL)


# --------------------------------------------------------------------------- #
# Stop AI: end every AI job now, including the request Karnak is working on.
# --------------------------------------------------------------------------- #
class Stopped(Exception):
    """Someone pressed Stop AI."""


STOPPED_MESSAGE = "The AI was stopped by hand."
_stop_count = 0           # goes up by one each time Stop AI is pressed
_local = threading.local()  # the stop count when this thread's job began
_live: set = set()        # connections to Karnak that are open right now
_live_lock = threading.Lock()


def begin_job(job_id: str | None = None) -> int:
    """Mark the start of an AI job in this thread; a later Stop AI ends it. `job_id`
    lets progress() tell which job Karnak is working on."""
    _local.started = _stop_count
    _local.job_id = job_id
    return _stop_count


# --------------------------------------------------------------------------- #
# Progress: what Karnak is doing for a job right now, for the loading meter
# --------------------------------------------------------------------------- #
# Karnak's speeds on this computer (tokens per second), learnt from its own timings
# after every request; the starting values are an ordinary laptop's.
RATES = {"read": 11.0, "write": 2.5}
_inflight: dict = {}  # the request Karnak is working on: {"job": id, "since": time}
_seen: dict = {}      # job id -> (time, tokens read, tokens written) at the last look
_peak: dict = {}      # job id -> highest percentage shown, so the bar never goes back


def _learn_rates(body: dict) -> None:
    t = body.get("timings") or {}
    for key, n, rate in (("read", t.get("prompt_n", 0), t.get("prompt_per_second")),
                         ("write", t.get("predicted_n", 0), t.get("predicted_per_second"))):
        if rate and n >= 100:  # short bursts don't show the real speed
            RATES[key] = round(0.6 * RATES[key] + 0.4 * float(rate), 2)


def progress(job_id: str, expected_out: int) -> dict:
    """{phase, read, read_total, written, expected_out, eta_seconds} for a running job.
    phase: "waiting" (Karnak is busy with another step), "reading" or "writing"."""
    if _inflight.get("job") != job_id:
        return {"phase": "waiting"}
    try:
        slot = httpx.get(BASE_URL.removesuffix("/v1") + "/slots", timeout=2).json()[0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return {"phase": "reading"}
    total = int(slot.get("n_prompt_tokens") or 0)
    cached = int(slot.get("n_prompt_tokens_cache") or 0)
    done = int(slot.get("n_prompt_tokens_processed") or 0)
    written = int(((slot.get("next_token") or [{}])[0]).get("n_decoded") or 0)
    to_read = max(0, total - cached)
    reading = written == 0 and done < to_read
    # Measure the real speed live from how far the counters moved since the last look,
    # so the time left follows this computer right now (on battery it is far slower).
    now, last = time.time(), _seen.get(job_id)
    if last and now - last[0] >= 2:
        dt = now - last[0]
        if done > last[1] and reading:
            RATES["read"] = round(0.5 * RATES["read"] + 0.5 * (done - last[1]) / dt, 2)
        if written > last[2]:
            RATES["write"] = round(0.5 * RATES["write"] + 0.5 * (written - last[2]) / dt, 2)
    if not last or now - last[0] >= 2:
        _seen.clear()
        _seen[job_id] = (now, done, written)
    left_read = max(0, to_read - done) if reading else 0
    left_write = max(0, expected_out - written)
    rr, rw = max(RATES["read"], 0.5), max(RATES["write"], 0.3)
    eta = left_read / rr + left_write / rw
    # The share of the work done, with fixed weights for reading and writing (an
    # ordinary laptop's proportions), so the bar only moves forward.
    w_read, w_write = to_read / 11.0, max(expected_out, written) / 2.5
    done_work = (to_read - left_read) / 11.0 + min(written, expected_out) / 2.5
    percent = 100 * done_work / (w_read + w_write) if (w_read + w_write) else 0
    percent = max(percent, _peak.get(job_id, 0))
    _peak.clear()
    _peak[job_id] = percent
    return {"phase": "reading" if reading else "writing", "read": min(done, to_read) if reading else to_read,
            "read_total": to_read, "written": written, "expected_out": expected_out,
            "eta_seconds": int(eta), "percent": round(min(99, max(1, percent)))}


def join_job(started: int) -> None:
    """A helper thread working for a job started at `started` (see begin_job)."""
    _local.started = started


def _check(started: int) -> None:
    if _stop_count != started:
        raise Stopped(STOPPED_MESSAGE)


def stop_all() -> int:
    """End every AI job. Returns how many requests to Karnak were cut off."""
    global _stop_count
    _stop_count += 1
    with _live_lock:
        clients = list(_live)
    for c in clients:
        _hang_up(c)
    return len(clients)


def _hang_up(client: httpx.Client) -> None:
    """Close a connection that may be waiting on Karnak. Karnak sees the caller gone
    and drops the request, so it is free for the next one."""
    try:
        for conn in client._transport._pool.connections:  # httpx keeps these private
            stream = getattr(getattr(conn, "_connection", None), "_network_stream", None)
            sock = getattr(stream, "_sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)  # wakes the thread that is waiting on it
    except Exception:
        pass
    try:
        client.close()
    except Exception:
        pass


def _post(payload: dict, headers: dict, timeout: float, started: int) -> httpx.Response:
    client = httpx.Client(timeout=timeout)
    with _live_lock:
        _live.add(client)
    job_id = getattr(_local, "job_id", None)
    try:
        _check(started)
        _inflight.update(job=job_id, since=time.time())
        resp = client.post(CHAT_URL, json=payload, headers=headers)
        try:
            _learn_rates(resp.json())
        except ValueError:
            pass
        return resp
    except Exception:
        _check(started)  # hung up by Stop AI: say so, not "connection closed"
        raise
    finally:
        if _inflight.get("job") == job_id:
            _inflight.clear()
        with _live_lock:
            _live.discard(client)
        client.close()
_MIN_SPEECH_TOKENS = 500
_EXCERPTS = 8


def _api_key() -> str | None:
    return os.environ.get("LLM_API_KEY")


def _model() -> str:
    return os.environ.get("LLM_MODEL") or DEFAULT_MODEL

TRAITS = ("BACE", "PWR", "CC", "SC", "TASK", "DIS", "IGB")

_SYSTEM_PROMPT = """You are an expert in Margaret Hermann's Leadership Trait \
Analysis (LTA). Given a political leader's speech, rate the leader on each of \
the seven LTA traits by reading the psychology and tone of the text -- not by \
counting keywords. Judge meaning, not vocabulary.

Traits (score 0-100, where 50 is average for a world leader):
- BACE: Belief in ability to control events. High = takes charge, initiates, \
shapes outcomes, "we decide our destiny". Low = reactive, waits, defers.
- PWR: Need for power. High = dominating, asserting authority, outmaneuvering, \
controlling others. Low = collaborative, shares influence.
- CC: Conceptual complexity. High = nuance, multiple perspectives, conditionals, \
uncertainty, trade-offs. Low = absolutes, black-and-white, certainty.
- SC: Self-confidence. High = self-assured, "I know", personal authority. \
Low = self-doubt, defers to others/context.
- TASK: Task vs relationship focus. High = problems, goals, getting things done. \
Low = people, feelings, morale, group maintenance.
- DIS: Distrust of others. High = suspicion, threat perception, enemies, betrayal. \
Low = trusting, sees others as partners.
- IGB: In-group bias. High = us-vs-them, strong national/group pride, outsiders \
as threats. Low = inclusive, sees shared humanity, low nationalism.

Respond ONLY with JSON of this exact shape:
{"traits": {"BACE": {"score": <0-100>, "band": "High|Moderate|Low", \
"rationale": "<one sentence>"}, ... all seven ...}, \
"leadership_style": "<short phrase>", "summary": "<one to two sentences>"}"""

# Human-readable names for languages we let the model write prose in.
_LANG_NAMES = {"en": "English", "ar": "Arabic"}


def _language_instruction(language: str) -> str:
    name = _LANG_NAMES.get(language, language)
    if language == "en":
        return ""
    return (
        f"\n\nWrite the 'rationale', 'summary', and 'leadership_style' field "
        f"values in {name}. Keep all JSON keys and the 'band' values exactly as "
        f"English (High / Moderate / Low)."
    )


def input_note(text: str) -> tuple[dict, str]:
    """Detect the speech's language/dialect; return it and a prompt note.

    The note tells the model what it is reading and that colloquial Egyptian is
    a register, not a signal about the speaker's traits.
    """
    detected = arabic.detect(text)
    if detected["language"] != "ar":
        return detected, ""
    return detected, (
        "\n\nThe speech is in Arabic -- detected as "
        f"{arabic.DIALECT_NAMES[detected['dialect']]} (a heuristic estimate). "
        "Read it in the original; do not translate first. Judge it on the same "
        "terms you would an English speech. Colloquial Egyptian phrasing is a "
        "register choice: do not read it as lower complexity, weaker task "
        "focus, or less confidence on its own."
    )


def _length_note(text: str) -> str:
    """Weigh the evidence like the dictionary scorer does: short text, scores near 50."""
    words = len(text.split())
    return (
        f"\n\nThe speech is {words} words long. Score on the strength of the "
        "evidence: a short text shows little, so keep scores near 50 unless a "
        "trait appears clearly and repeatedly; a long text with consistent "
        "signals can earn extreme scores. A single strong sentence is not a "
        "profile."
    )


def estimate_tokens(text: str) -> int:
    """Rough token count, on the high side: Arabic takes more tokens per character."""
    return int(len(text) / (2.5 if arabic.is_arabic(text) else 4))


def fit_speech(text: str, prompt: str = "", reserve: int | None = None) -> tuple[str, str, dict | None]:
    """Fit a speech into what's left of MAX_INPUT_TOKENS after the prompt.

    Returns (text to send, prompt note, {read_words, total_words} or None if the
    whole speech fits). A long document becomes evenly spaced excerpts cut at line
    or sentence ends, so the model sees all of it rather than just the start.
    """
    room = reserve if reserve is not None else estimate_tokens(prompt)
    budget = max(_MIN_SPEECH_TOKENS, MAX_INPUT_TOKENS - room)
    tokens = estimate_tokens(text)
    if tokens <= budget:
        return text, "", None
    step, size = len(text) // _EXCERPTS, int(len(text) * budget / tokens) // _EXCERPTS
    excerpts = []
    for i in range(_EXCERPTS):
        window = text[i * step:i * step + size]
        # Drop the broken sentence at each edge, if the window has a break to cut at.
        starts = [window.find(c) for c in ("\n", ". ", "\u061f", "\u060c") if c in window]
        start = min(starts) + 1 if starts and i else 0
        end = max(window.rfind(c) for c in ("\n", ".", "\u061f"))
        excerpts.append(window[start:end + 1 if end > start else len(window)].strip())
    sent = "\n\n[...]\n\n".join(excerpts)
    total, read = len(text.split()), len(sent.split())
    note = (f"\n\nThis is a long document of {total} words. You are given {_EXCERPTS} "
            f"evenly spaced excerpts ({read} words), separated by [...]. Judge the whole "
            "document from them.")
    return sent, note, {"read_words": read, "total_words": total}


# --------------------------------------------------------------------------- #
# Speech first: read once, reused by every request
# --------------------------------------------------------------------------- #
# Karnak keeps the start of its last prompt in memory and skips re-reading it when the
# next prompt starts the same way. So the AI traits and the stakeholder reactions both
# open with the same system line and the same speech text, and put their own task
# after it: the reactions then reuse the speech Karnak just read for the traits,
# instead of reading it again (several minutes on an ordinary computer).
ANALYST_SYSTEM = ("You are Cortex, a political analyst. Read the speech or document first, then do "
                  "the task written after it. Respond ONLY with JSON.")
# Room kept for the task (instructions, stakeholder profiles) when fitting the speech:
# the same for every request, so long speeches are cut into the same excerpts.
SPEECH_RESERVE = 3000


def speech_messages(text: str, task: str) -> tuple[list[dict], dict | None]:
    """Chat messages with the speech first and the task after it; and the excerpt info."""
    sent, note, excerpted = fit_speech(text, reserve=SPEECH_RESERVE)
    user = f"SPEECH OR DOCUMENT:\n\n{sent}\n\n==========\nTASK\n\n{task}{note}"
    return [{"role": "system", "content": ANALYST_SYSTEM}, {"role": "user", "content": user}], excerpted


# Size of one part when a long document is read part by part (see split_parts).
PART_TOKENS = int(os.environ.get("LLM_PART_TOKENS") or 3500)


def split_parts(text: str, size: int = PART_TOKENS) -> list[str]:
    """Cut a text into consecutive parts of about `size` tokens, at line or sentence
    ends, so together they hold every word exactly once."""
    pieces = re.findall(r"[^\n.!?\u061f]*(?:[\n.!?\u061f]+\s*|$)", text)
    parts: list[str] = []
    cur = ""
    for piece in pieces:
        if not piece:
            continue
        if cur and estimate_tokens(cur + piece) > size:
            parts.append(cur)
            cur = ""
        cur += piece
        # A run with no sentence end at all: cut it by length.
        while estimate_tokens(cur) > size:
            cut = int(len(cur) * size / estimate_tokens(cur))
            parts.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


class LLMNotConfigured(RuntimeError):
    """Raised when no AI provider is configured."""


def available() -> bool:
    # The local server needs no key; whether it is running shows on the first call.
    return bool(BASE_URL)


def not_configured_reason() -> str:
    return "No AI server configured (set LLM_BASE_URL)."


def not_running_reason() -> str:
    return ("The local AI (Karnak) is not running. Start it with: llama-server -m "
            "Karnak-6B-v1.0.Q4_K_M.gguf -c 16384 -np 1 --port 8080 --alias karnak-6b")


# Other models to try when the main one fails (comma-separated). None by default:
# the local server runs a single model.
FALLBACK_MODELS = [m.strip() for m in (os.environ.get("LLM_FALLBACK_MODELS") or "").split(",") if m.strip()]


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", 10))
    except ValueError:
        return 10.0


def chat_json(messages: list[dict], temperature: float, model: str | None = None,
              timeout: float | None = None, reasoning_effort: str | None = None,
              max_wait: float = 20.0) -> tuple[dict, str]:
    """POST a JSON-mode chat; return (parsed content, model actually used).

    On a rate limit (429): try each of FALLBACK_MODELS, then wait out the
    primary's retry-after once (if <= max_wait seconds) and try it again.
    """
    if not available():
        raise LLMNotConfigured(not_configured_reason())
    started = getattr(_local, "started", None)
    started = _stop_count if started is None else started
    _check(started)
    api_key = _api_key()
    timeout = timeout or TIMEOUT
    primary = model or _model()
    plan = [primary] + [m for m in FALLBACK_MODELS if m != primary] + [primary]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    wait: float | None = None  # set only if the primary was rate-limited
    error: Exception | None = None
    for i, m in enumerate(plan):
        if i == len(plan) - 1:  # final retry of the primary, after its cooldown
            if wait is None or wait > max_wait:
                break
            time.sleep(wait)
        payload = {"model": m, "temperature": temperature,
                   "response_format": {"type": "json_object"}, "messages": messages}
        if reasoning_effort and m.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = reasoning_effort
        try:
            with _TURN:
                resp = _post(payload, headers, timeout, started)
            if resp.status_code == 429 and i == 0:
                wait = _retry_after(resp)
            resp.raise_for_status()
            return json.loads(resp.json()["choices"][0]["message"]["content"]), m
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            error = exc  # rate limit, retired model, bad JSON: try the next one
    raise error


def score_llm(text: str, model: str | None = None, timeout: float | None = None,
              language: str = "en") -> dict:
    """Rate the seven LTA traits semantically via the LLM. Returns parsed JSON.

    `language` controls the prose fields (rationale/summary/leadership_style);
    scores, keys and bands stay English.
    """
    detected, note = input_note(text)
    task = (_SYSTEM_PROMPT + note + _length_note(text) + _language_instruction(language)
            + "\n\nScore the speech above.")
    messages, excerpted = speech_messages(text, task)
    data, model = chat_json(messages, temperature=0.2, model=model, timeout=timeout)
    # Small models sometimes misspell a key; accept the near-misses.
    for k in list(data):
        if k != "leadership_style" and k.replace("_", "").lower() == "leadershipstyle":
            data.setdefault("leadership_style", data.pop(k))
    data["model"] = model
    data["excerpted"] = excerpted
    data["method"] = "llm"
    data["language"] = language
    data["input"] = detected
    return data


if __name__ == "__main__":
    from .mock_speeches import MOCK_SPEECHES
    sample = MOCK_SPEECHES["P1_Expansionist_Crusader"]["text"]
    result = score_llm(sample)
    print(f"model={result['model']}  style={result.get('leadership_style')}")
    for t in TRAITS:
        tr = result["traits"][t]
        print(f"  {t:5} {tr['score']:3}  {tr['band']:8}  {tr['rationale']}")
