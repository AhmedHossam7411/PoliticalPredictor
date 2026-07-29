"""One-time calibration: distill each stakeholder's baseline speech into a compact
decision profile, cached to predictor/baseline_profiles.json.

The reaction simulator (stakeholders.py) loads that cache so its predictions are
grounded in how each stakeholder actually thinks and speaks -- not just the short
bio -- without shipping ~10k-character speeches into every request.

Run once (re-run to refresh):  python -m predictor.calibrate_baselines
Requires GROQ_API_KEY.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from .llm import GROQ_URL, DEFAULT_MODEL, LLMNotConfigured
from .stakeholders import STAKEHOLDERS

ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "baseline_speeches"
OUT = Path(__file__).resolve().parent / "baseline_profiles.json"

_SYSTEM = """You are building a detailed DECISION PROFILE of a person from their own \
baseline speech, so another model can accurately predict how THIS specific person \
would react to future speeches or policies. Read the whole speech carefully and \
preserve their nuance, conditions, and caveats -- do not flatten them into generic \
traits. Capture not just WHAT they conclude but HOW and WHY they reason.

Respond ONLY with JSON of this exact shape:
{"worldview": "<3-5 sentences on their core philosophy and how they see the world>",
 "priorities": ["<6-9 short phrases: what they care most about, most important first>"],
 "decision_style": "<3-4 sentences: how they weigh options, what evidence or \
conditions they demand, how they handle uncertainty and trade-offs>",
 "values_and_redlines": "<2-3 sentences: their non-negotiables -- what reliably \
earns their trust, and what they will not accept under any framing>",
 "tone": "<1-2 sentences on their rhetorical tone and temperament>",
 "reaction_tendencies": "<3-5 sentences: specifically what wins their SUPPORT versus \
their RESISTANCE, including the conditions that flip them (e.g. same idea done \
abruptly vs. gradually)>",
 "key_quotes": ["<4-6 short sentences copied VERBATIM (word-for-word) from the \
speech that best reveal how this person thinks>"]}

The key_quotes must be exact substrings of the speech, not paraphrased."""


def distill(name: str, role: str, speech: str, timeout: float = 90.0) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY environment variable is not set.")
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",
             "content": f"Person: {name} ({role}).\n\nBaseline speech:\n\n{speech}"},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(6):
        resp = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", 20)) + 1
            print(f"    429 rate-limited; waiting {wait:.0f}s...", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])
    raise RuntimeError("giving up after repeated 429s")


def main() -> None:
    # Resume: keep any profiles already distilled in a previous run.
    profiles: dict[str, dict] = {}
    if OUT.exists():
        profiles = json.loads(OUT.read_text(encoding="utf-8"))

    for s in STAKEHOLDERS:
        if s["id"] in profiles:
            print(f"  have {s['id']} (cached)")
            continue
        path = BASELINE_DIR / f"{s['id']}.txt"
        if not path.exists():
            print(f"  skip {s['id']}: no baseline file")
            continue
        speech = path.read_text(encoding="utf-8")
        print(f"  distilling {s['id']} ({len(speech)} chars)...", flush=True)
        prof = distill(s["name"], s["role"], speech)
        prof["source"] = path.name
        profiles[s["id"]] = prof
        # Save after every success so a rate-limit crash never loses progress.
        OUT.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(3)  # be gentle on the rate limit

    print(f"\nWrote {len(profiles)} profiles -> {OUT}")


if __name__ == "__main__":
    main()
