"""Groq LLM scorer for LTA traits -- the semantic complement to the dictionary.

The dictionary scorer only sees vocabulary; this reads *meaning*, so it rates a
speech that is "high power" in tone even when it uses no literal power words.
Returns the same seven traits on a 0-100 scale plus a short rationale each.

Requires the GROQ_API_KEY environment variable. Uses Groq's OpenAI-compatible
chat API via httpx (no extra dependency). Model via GROQ_MODEL (default
llama-3.3-70b-versatile).
"""
from __future__ import annotations

import json
import os

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

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


class LLMNotConfigured(RuntimeError):
    """Raised when GROQ_API_KEY is missing."""


def available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def score_llm(text: str, model: str | None = None, timeout: float = 60.0,
              language: str = "en") -> dict:
    """Rate the seven LTA traits semantically via Groq. Returns parsed JSON.

    `language` controls the prose fields (rationale/summary/leadership_style);
    scores, keys and bands stay English.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY environment variable is not set.")
    model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT + _language_instruction(language)},
            {"role": "user", "content": f"Score this speech:\n\n{text}"},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    data["model"] = model
    data["method"] = "llm"
    data["language"] = language
    return data


if __name__ == "__main__":
    from .mock_speeches import MOCK_SPEECHES
    sample = MOCK_SPEECHES["P1_Expansionist_Crusader"]["text"]
    result = score_llm(sample)
    print(f"model={result['model']}  style={result.get('leadership_style')}")
    for t in TRAITS:
        tr = result["traits"][t]
        print(f"  {t:5} {tr['score']:3}  {tr['band']:8}  {tr['rationale']}")
