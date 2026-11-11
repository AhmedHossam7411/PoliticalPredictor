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
import time

import httpx

from . import arabic

LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
BASE_URL = (os.environ.get("LLM_BASE_URL") or LOCAL_BASE_URL).rstrip("/")
CHAT_URL = BASE_URL + "/chat/completions"
DEFAULT_MODEL = "karnak-6b"
# A model on an ordinary computer is slow: allow up to an hour per call.
TIMEOUT = float(os.environ.get("LLM_TIMEOUT") or 3600)
# Most input tokens to send in one call. Karnak is started with a 16k context,
# which leaves room for the prompt and the answer.
MAX_INPUT_TOKENS = int(os.environ.get("LLM_MAX_INPUT_TOKENS") or 7500)
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


def fit_speech(text: str, prompt: str = "") -> tuple[str, str, dict | None]:
    """Fit a speech into what's left of MAX_INPUT_TOKENS after the prompt.

    Returns (text to send, prompt note, {read_words, total_words} or None if the
    whole speech fits). A long document becomes evenly spaced excerpts cut at line
    or sentence ends, so the model sees all of it rather than just the start.
    """
    budget = max(_MIN_SPEECH_TOKENS, MAX_INPUT_TOKENS - estimate_tokens(prompt))
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
            "Karnak-6B-v1.0.Q4_K_M.gguf -c 16384 --port 8080 --alias karnak-6b")


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
            resp = httpx.post(CHAT_URL, json=payload, headers=headers, timeout=timeout)
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
    system = _SYSTEM_PROMPT + note + _length_note(text) + _language_instruction(language)
    sent, excerpt_note, excerpted = fit_speech(text, system)
    data, model = chat_json([
        {"role": "system", "content": system + excerpt_note},
        {"role": "user", "content": f"Score this speech:\n\n{sent}"},
    ], temperature=0.2, model=model, timeout=timeout)
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
