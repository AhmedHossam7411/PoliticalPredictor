"""Groq LLM scorer for LTA traits -- the semantic complement to the dictionary.

The dictionary scorer only sees vocabulary; this reads *meaning*, so it rates a
speech that is "high power" in tone even when it uses no literal power words.
Returns the same seven traits on a 0-100 scale plus a short rationale each.

Requires the GROQ_API_KEY environment variable. Uses Groq's OpenAI-compatible
chat API via httpx (no extra dependency). Model via GROQ_MODEL (default
openai/gpt-oss-120b; llama-3.3-70b-versatile was retired by Groq).
"""
from __future__ import annotations

import json
import os
import time

import httpx

from . import arabic

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"

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


class LLMNotConfigured(RuntimeError):
    """Raised when GROQ_API_KEY is missing."""


def available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


# Groq's free tier caps tokens per minute *per model* (8k each). The trait
# scorer and the stakeholder call (~7k tokens) fire together, so a 429 is
# routine; other models have their own quotas and are tried first.
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", 10))
    except ValueError:
        return 10.0


def chat_json(messages: list[dict], temperature: float, model: str | None = None,
              timeout: float = 60.0, reasoning_effort: str | None = None,
              max_wait: float = 20.0) -> tuple[dict, str]:
    """POST a JSON-mode chat to Groq; return (parsed content, model actually used).

    On a rate limit (429): try each of FALLBACK_MODELS, then wait out the
    primary's retry-after once (if <= max_wait seconds) and try it again.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY environment variable is not set.")
    primary = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    plan = [primary] + [m for m in FALLBACK_MODELS if m != primary] + [primary]

    headers = {"Authorization": f"Bearer {api_key}"}
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
            resp = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 429 and i == 0:
                wait = _retry_after(resp)
            resp.raise_for_status()
            return json.loads(resp.json()["choices"][0]["message"]["content"]), m
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            error = exc  # rate limit, retired model, bad JSON: try the next one
    raise error


def score_llm(text: str, model: str | None = None, timeout: float = 60.0,
              language: str = "en") -> dict:
    """Rate the seven LTA traits semantically via Groq. Returns parsed JSON.

    `language` controls the prose fields (rationale/summary/leadership_style);
    scores, keys and bands stay English.
    """
    detected, note = input_note(text)
    data, model = chat_json([
        {"role": "system",
         "content": _SYSTEM_PROMPT + note + _language_instruction(language)},
        {"role": "user", "content": f"Score this speech:\n\n{text}"},
    ], temperature=0.2, model=model, timeout=timeout)
    data["model"] = model
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
