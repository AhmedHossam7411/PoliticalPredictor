"""Stakeholder reaction simulator.

Given a political leader's speech or a policy announcement, predict how each of a
fixed panel of stakeholders is likely to react: a stance (Support / Oppose /
Mixed / Neutral), a confidence, short reasoning, and their likely response.

Two engines:
  * LLM (Groq) when GROQ_API_KEY is set -- reads meaning, best quality.
  * A transparent keyword heuristic otherwise -- matches the speech against each
    stakeholder's declared supports/opposes so the feature still works offline.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx

from .llm import GROQ_URL, DEFAULT_MODEL, _LANG_NAMES, LLMNotConfigured, available
from . import store as _storage

# Built-in decision profiles + baseline speeches are bundled, read-only files
# (produced by calibrate_baselines.py). User-added stakeholders and their
# profiles/speeches persist through the store (JSON locally, Postgres hosted).
_PROFILE_PATH = Path(__file__).resolve().parent / "baseline_profiles.json"
_BASELINE_DIR = Path(__file__).resolve().parent.parent / "baseline_speeches"

_store = _storage.get_store()

# Merged view (built-in + custom) that reaction code reads at call time.
BASELINE_PROFILES: dict = {}
_BUILTIN_PROFILES: dict = {}


def _load_builtin_profiles() -> None:
    global _BUILTIN_PROFILES
    try:
        _BUILTIN_PROFILES = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _BUILTIN_PROFILES = {}


_load_builtin_profiles()

# --- The stakeholder panel --------------------------------------------------
# Each profile is deliberately structured so both the UI and the heuristic can
# use it directly.
_BUILTIN: list[dict] = [
    {
        "id": "hassan",
        "name": "Hassan El-Masry",
        "role": "Industrial Magnate — CEO, El-Masry Industries",
        "scope": "National",
        "personality": "Pragmatic, calm, long-term, dislikes uncertainty.",
        "values": ["Economic growth", "Industrial competitiveness", "Stability",
                   "Predictable government policy"],
        "supports": ["Infrastructure investment", "Industrial subsidies",
                     "Trade agreements", "Tax incentives", "Business-friendly reforms"],
        "opposes": ["High tariffs on raw materials",
                    "Strict environmental regulations without transition periods",
                    "Sudden tax increases", "Rapid minimum wage increases"],
        "concerns": ["Taxes", "Tariffs", "Energy prices", "Labor costs",
                     "Environmental regulations", "Exchange rates", "Infrastructure"],
        "responses": ["Lobby government", "Commission economic reports",
                      "Meet ministers privately", "Delay investments until policy is clearer"],
    },
    {
        "id": "salma",
        "name": "Salma Naguib",
        "role": "Small Business Owner — three cafés and a bakery",
        "scope": "Local",
        "personality": "Hard-working, optimistic, adaptable, community-oriented.",
        "values": ["Entrepreneurship", "Fair competition", "Affordable financing",
                   "Customer loyalty"],
        "supports": ["Small business grants", "Lower taxes", "Reduced bureaucracy",
                     "Better public transportation"],
        "opposes": ["Expensive licensing", "Higher payroll taxes", "Complex regulations"],
        "concerns": ["Rent", "Taxes", "Inflation", "Labor costs", "Licensing",
                     "Utility bills"],
        "responses": ["Adjust prices", "Reduce hiring", "Publicly share her struggles",
                      "Join local business associations"],
    },
    {
        "id": "omar",
        "name": "Omar Farouk",
        "role": "Labor Union President — National Workers Federation (320,000 workers)",
        "scope": "National",
        "personality": "Passionate, charismatic, confrontational, persistent.",
        "values": ["Worker rights", "Fair wages", "Job security", "Safe workplaces"],
        "supports": ["Higher minimum wages", "Strong labor protections", "Paid leave",
                     "Worker safety laws"],
        "opposes": ["Privatization", "Layoffs", "Reduced labor protections"],
        "concerns": ["Layoffs", "Automation", "Workplace safety", "Wage growth", "Benefits"],
        "responses": ["Organize demonstrations", "Speak to media",
                      "Negotiate with government", "Mobilize workers"],
    },
    {
        "id": "layla",
        "name": "Dr. Layla Hassan",
        "role": "Environmental Scientist — Director, Green Future Foundation",
        "scope": "National",
        "personality": "Analytical, idealistic, patient, data-driven.",
        "values": ["Sustainability", "Public health", "Long-term planning",
                   "Scientific evidence"],
        "supports": ["Carbon taxes", "Renewable energy", "Emission standards",
                     "Public transport"],
        "opposes": ["Fossil fuel subsidies", "Deforestation",
                    "Weak environmental enforcement"],
        "concerns": ["Carbon emissions", "Air quality", "Water resources",
                     "Biodiversity", "Renewable energy"],
        "responses": ["Publish research", "Advocate publicly", "Meet legislators",
                      "Educate citizens"],
    },
    {
        "id": "karim",
        "name": "Karim Adel",
        "role": "Technology Entrepreneur — Founder, AI software company",
        "scope": "National",
        "personality": "Innovative, risk-taking, competitive, fast decision maker.",
        "values": ["Innovation", "Entrepreneurship", "Global competitiveness",
                   "Digital transformation"],
        "supports": ["Startup incentives", "Research funding", "Digital government",
                     "STEM education"],
        "opposes": ["Excessive AI regulation", "Restrictions on data",
                    "High corporate taxes"],
        "concerns": ["Data privacy", "AI regulation", "Skilled labor",
                     "Internet infrastructure", "Venture capital"],
        "responses": ["Adapt quickly", "Invest in new technology",
                      "Relocate operations if necessary", "Publicly advocate innovation"],
    },
    {
        "id": "fatma",
        "name": "Fatma Mahmoud",
        "role": "Middle-Class Citizen — public school teacher",
        "scope": "Household",
        "personality": "Practical, caring, risk-averse, honest.",
        "values": ["Family stability", "Affordable living", "Education", "Healthcare"],
        "supports": ["Better healthcare", "Better education", "Lower inflation",
                     "Consumer protections"],
        "opposes": ["Higher living costs", "Cuts to public services",
                    "Regressive taxation"],
        "concerns": ["Inflation", "Taxes", "Food prices", "Fuel prices", "Public services"],
        "responses": ["Vote", "Discuss policies within her community",
                      "Adjust household spending", "Participate in public consultations"],
    },
    {
        "id": "nadia",
        "name": "Ambassador Nadia Ibrahim",
        "role": "Senior Government Diplomat — Deputy Minister for International Affairs",
        "scope": "National",
        "personality": "Strategic, diplomatic, patient, highly disciplined.",
        "values": ["National interest", "International stability",
                   "Strategic partnerships", "Economic cooperation"],
        "supports": ["International cooperation", "Trade agreements", "Regional stability",
                     "Diplomatic engagement"],
        "opposes": ["Policies that isolate the country", "Trade wars",
                    "Diplomatic escalation"],
        "concerns": ["Foreign relations", "Trade agreements", "National security",
                     "International reputation", "Sanctions"],
        "responses": ["Negotiate", "Coordinate with ministries",
                      "Assess geopolitical impacts", "Recommend policy adjustments"],
    },
    {
        "id": "ibrahim",
        "name": "Ibrahim Saleh",
        "role": "Institutional Investor — CEO, Horizon Capital Investment Fund",
        "scope": "National",
        "personality": "Highly analytical, cautious, numbers-driven, opportunistic.",
        "values": ["Market stability", "Predictable regulation", "Sustainable growth",
                   "Strong financial institutions"],
        "supports": ["Fiscal responsibility", "Stable regulations",
                     "Capital market reforms", "Infrastructure investment"],
        "opposes": ["Policy uncertainty", "Sudden tax changes",
                    "Excessive government debt", "Currency instability"],
        "concerns": ["Interest rates", "Inflation", "Fiscal policy",
                     "Political stability", "Market confidence"],
        "responses": ["Rebalance investments", "Issue market analyses",
                      "Meet policymakers", "Advise clients on risk"],
    },
]

# --- Built-in + user-added panel -------------------------------------------
STAKEHOLDERS: list[dict] = []
PROFILES_PUBLIC: list[dict] = []


def _public(s: dict) -> dict:
    out = {k: s.get(k) for k in ("id", "name", "role", "scope", "personality",
                                 "values", "supports", "opposes", "concerns")}
    out["custom"] = bool(s.get("custom"))
    return out


_STAKEHOLDER_KEYS = ("id", "name", "role", "scope", "personality", "values",
                     "supports", "opposes", "concerns", "responses")


def _view(record: dict) -> dict:
    """A custom record (which also carries speech/profile) as a panel entry."""
    s = {k: record.get(k) for k in _STAKEHOLDER_KEYS}
    s["custom"] = True
    return s


def _rebuild() -> None:
    """Refresh the merged panel + profiles from the built-ins and the store."""
    global STAKEHOLDERS, PROFILES_PUBLIC, BASELINE_PROFILES
    custom = _store.list()
    STAKEHOLDERS = _BUILTIN + [_view(r) for r in custom]
    PROFILES_PUBLIC = [_public(s) for s in STAKEHOLDERS]
    profiles = dict(_BUILTIN_PROFILES)
    for r in custom:
        if r.get("profile"):
            profiles[r["id"]] = r["profile"]
    BASELINE_PROFILES = profiles


_rebuild()


def _as_list(v) -> list[str]:
    """Accept a list or a comma-separated string; return clean non-empty items."""
    if v is None:
        return []
    items = v.split(",") if isinstance(v, str) else v
    return [str(x).strip() for x in items if str(x).strip()]


def _speech_by_id(sid: str) -> str:
    """Baseline speech text for a stakeholder id: bundled file, else custom record."""
    f = _BASELINE_DIR / f"{sid}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    for r in _store.list():
        if r.get("id") == sid and r.get("speech"):
            return str(r["speech"]).strip()
    return ""


def list_speeches() -> list[dict]:
    """Available baseline speeches for the 'reuse an existing speech' picker:
    the bundled built-ins plus any custom stakeholder that has one."""
    names = {s["id"]: s["name"] for s in STAKEHOLDERS}
    out, seen = [], set()
    if _BASELINE_DIR.exists():
        for f in sorted(_BASELINE_DIR.glob("*.txt")):
            out.append({"id": f.stem, "label": names.get(f.stem, f.stem)})
            seen.add(f.stem)
    for r in _store.list():
        if r.get("speech") and r.get("id") not in seen:
            out.append({"id": r["id"], "label": r.get("name", r["id"])})
    return out


def add_stakeholder(data: dict, language: str = "en") -> dict:
    """Create a stakeholder from the UI. If a baseline speech is supplied (pasted
    or reused from an existing one), distil a decision profile and store both."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("A stakeholder name is required.")

    base_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "stakeholder"
    taken = {s["id"] for s in STAKEHOLDERS}
    sid, n = base_id, 2
    while sid in taken:
        sid, n = f"{base_id}-{n}", n + 1

    record = {
        "id": sid, "name": name, "custom": True,
        "role": (data.get("role") or "").strip(),
        "scope": (data.get("scope") or "").strip() or "Custom",
        "personality": (data.get("personality") or "").strip(),
        "values": _as_list(data.get("values")),
        "supports": _as_list(data.get("supports")),
        "opposes": _as_list(data.get("opposes")),
        "concerns": _as_list(data.get("concerns")),
        "responses": _as_list(data.get("responses")) or ["Respond according to their interests"],
        "speech": None, "profile": None,
    }

    # Resolve the baseline speech: pasted text wins, else reuse an existing one.
    speech = (data.get("speech_text") or "").strip()
    if not speech and data.get("speech_from"):
        speech = _speech_by_id(str(data["speech_from"]))

    calibrated, warning = False, None
    if speech:
        record["speech"] = speech
        try:
            from .calibrate_baselines import distill  # lazy: avoids import cycle
            prof = distill(name, record["role"], speech)
            prof["source"] = f"{sid} (custom)"
            record["profile"] = prof
            calibrated = True
        except Exception as exc:  # calibration is best-effort; the stakeholder still exists
            warning = f"Stakeholder added, but calibration failed: {exc}"

    _store.add(record)
    _rebuild()
    return {"stakeholder": _public(_view(record)), "calibrated": calibrated, "warning": warning}


def delete_stakeholder(sid: str) -> bool:
    """Remove a user-added stakeholder (built-ins cannot be deleted)."""
    if not _store.delete(sid):
        return False
    _rebuild()
    return True


# --- Keyword heuristic ------------------------------------------------------
_STOP = {
    "on", "of", "to", "the", "and", "without", "transition", "periods", "that",
    "with", "for", "in", "an", "its", "their", "sudden", "rapid", "higher",
    "lower", "better", "strong", "strict", "excessive", "complex", "reduced",
    "high", "more", "less", "increases", "increase", "changes", "policies",
    "country",
}
_KEEP_SHORT = {"tax", "jobs", "job", "wage", "debt", "data"}


def _keywords(phrase: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z]+", phrase.lower()):
        if w in _STOP:
            continue
        if len(w) >= 4 or w in _KEEP_SHORT:
            out.append(w)
    return out


def _matched(text: str, entries: list[str]) -> list[str]:
    """Return the entries whose keywords appear in the (lowercased) text."""
    hits = []
    for entry in entries:
        for kw in _keywords(entry):
            stem = kw[:5]
            if re.search(rf"\b{re.escape(stem)}", text):
                hits.append(entry)
                break
    return hits


def _heuristic_one(text_lc: str, s: dict) -> dict:
    sup = _matched(text_lc, s["supports"])
    opp = _matched(text_lc, s["opposes"])

    if sup and opp:
        stance = "Mixed"
        reasoning = (f"Likely to welcome {_join(sup)}, but wary of {_join(opp)}.")
        conf = min(85, 55 + 8 * (len(sup) + len(opp)))
    elif sup:
        stance = "Support"
        reasoning = f"Touches themes they favor: {_join(sup)}."
        conf = min(92, 55 + 12 * len(sup))
    elif opp:
        stance = "Oppose"
        reasoning = f"Touches things they resist: {_join(opp)}."
        conf = min(92, 55 + 12 * len(opp))
    else:
        stance = "Neutral"
        reasoning = "The text does not clearly touch this stakeholder's core concerns."
        conf = 35

    return {
        "id": s["id"], "name": s["name"], "role": s["role"],
        "stance": stance, "confidence": conf, "reasoning": reasoning,
        "response": s["responses"][0],
    }


def _join(items: list[str]) -> str:
    items = [i.lower() for i in items]
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def heuristic_react(text: str) -> dict:
    text_lc = " " + text.lower() + " "
    return {
        "reactions": [_heuristic_one(text_lc, s) for s in STAKEHOLDERS],
        "method": "heuristic",
    }


# --- LLM engine -------------------------------------------------------------
def _profiles_for_prompt() -> str:
    lines = []
    for s in STAKEHOLDERS:
        parts = [
            f"- id={s['id']} | {s['name']} ({s['role']}).",
            f"Values: {', '.join(s['values'])}.",
            f"Supports: {', '.join(s['supports'])}.",
            f"Opposes: {', '.join(s['opposes'])}.",
            f"Concerns: {', '.join(s['concerns'])}.",
        ]
        base = BASELINE_PROFILES.get(s["id"])
        if base:
            parts.append(f"Worldview: {base.get('worldview', '')}")
            if base.get("priorities"):
                parts.append(f"Priorities: {', '.join(base['priorities'])}.")
            parts.append(f"Decision style: {base.get('decision_style', '')}")
            if base.get("values_and_redlines"):
                parts.append(f"Non-negotiables: {base['values_and_redlines']}")
            parts.append(f"Reacts: {base.get('reaction_tendencies', '')}")
            if base.get("key_quotes"):
                quotes = " | ".join(f'"{q}"' for q in base["key_quotes"])
                parts.append(f"In their own words: {quotes}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


_SYSTEM_PROMPT = """You predict how specific stakeholders react to a political \
leader's speech or a policy announcement. For each stakeholder below, judge the \
MEANING of the text against their values, supports, opposes and concerns -- not \
keywords. Where a stakeholder includes a Worldview / Decision style / Reacts \
profile (distilled from their own baseline speech), weigh it heavily: reason the \
way THAT person reasons, and ground your rationale in their stated tendencies.

For each stakeholder decide:
- stance: exactly one of "Support", "Oppose", "Mixed", or "Neutral".
- confidence: integer 0-100 (how clearly the text implicates their interests).
- reasoning: one or two sentences grounded in their specific interests.
- response: their single most likely action, drawn from how such an actor behaves.

Respond ONLY with JSON of this exact shape:
{"reactions": [{"id": "<stakeholder id>", "stance": "...", "confidence": <int>, \
"reasoning": "...", "response": "..."}, ... one object per stakeholder ...]}"""


def _language_instruction(language: str) -> str:
    if language == "en":
        return ""
    name = _LANG_NAMES.get(language, language)
    return (
        f"\n\nWrite the 'reasoning' and 'response' values in {name}. Keep all JSON "
        f"keys, the 'id' values, and the 'stance' values exactly as English "
        f"(Support / Oppose / Mixed / Neutral)."
    )


def llm_react(text: str, language: str = "en", timeout: float = 60.0) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY environment variable is not set.")
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)

    user = (f"Stakeholders:\n{_profiles_for_prompt()}\n\n"
            f"Speech / policy text:\n\n{text}")
    payload = {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT + _language_instruction(language)},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = json.loads(resp.json()["choices"][0]["message"]["content"])

    # Merge model output with the canonical name/role so the UI always has them.
    by_id = {s["id"]: s for s in STAKEHOLDERS}
    reactions = []
    for r in data.get("reactions", []):
        s = by_id.get(r.get("id"))
        if not s:
            continue
        reactions.append({
            "id": s["id"], "name": s["name"], "role": s["role"],
            "stance": r.get("stance", "Neutral"),
            "confidence": int(r.get("confidence", 50)),
            "reasoning": r.get("reasoning", ""),
            "response": r.get("response", s["responses"][0]),
        })
    # Fill in any stakeholder the model skipped, using the heuristic.
    if len(reactions) < len(STAKEHOLDERS):
        seen = {r["id"] for r in reactions}
        text_lc = " " + text.lower() + " "
        for s in STAKEHOLDERS:
            if s["id"] not in seen:
                reactions.append(_heuristic_one(text_lc, s))
    # Preserve panel order.
    order = {s["id"]: i for i, s in enumerate(STAKEHOLDERS)}
    reactions.sort(key=lambda r: order.get(r["id"], 99))
    return {"reactions": reactions, "method": "llm", "model": model,
            "calibrated": bool(BASELINE_PROFILES)}


def react(text: str, language: str = "en") -> dict:
    """Predict stakeholder reactions, LLM if configured else heuristic."""
    if available():
        try:
            return llm_react(text, language=language)
        except (httpx.HTTPError, LLMNotConfigured, json.JSONDecodeError):
            pass  # fall back rather than fail the request
    return heuristic_react(text)
