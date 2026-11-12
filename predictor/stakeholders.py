"""Stakeholder reaction simulator.

Given a political leader's speech or a policy announcement, predict how each of a
fixed panel of stakeholders is likely to react: a stance (Support / Oppose /
Mixed / Neutral), a confidence, short reasoning, and their likely response.

Two engines:
  * LLM when an AI provider is configured (see llm.py) -- reads meaning, best quality.
  * A transparent keyword heuristic otherwise -- matches the speech against each
    stakeholder's declared supports/opposes so the feature still works offline.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .llm import (_LANG_NAMES, FALLBACK_MODELS, LLMNotConfigured, available, estimate_tokens,
                  fit_speech, input_note, chat_json, split_parts,
                  not_configured_reason, not_running_reason)
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
# Real public figures. Each profile summarises long-standing, publicly stated
# positions (no invented quotes or speeches) so both the UI and the heuristic can
# use it directly. Office-holders checked November 2026; review them as roles change.
# A real speech saved as baseline_speeches/<id>.txt calibrates that person.
_BUILTIN: list[dict] = [
    # ---- MENA leaders ----
    {
        "id": "sisi", "name": "Abdel Fattah el-Sisi", "role": "President of Egypt",
        "scope": "Egypt",
        "personality": "Public messaging stresses state stability, security and national "
                       "megaprojects; a cautious, state-led approach to reform.",
        "values": ["National security", "State stability", "Economic development", "Sovereignty"],
        "supports": ["National infrastructure megaprojects", "IMF-backed economic reform",
                     "Palestinian statehood", "Gaza ceasefire and reconstruction",
                     "Counter-terrorism cooperation", "Foreign investment in Egypt"],
        "opposes": ["Displacement of Palestinians into Sinai", "Political Islamist movements",
                    "Foreign interference in Egyptian affairs",
                    "Unilateral Nile dam filling without agreement"],
        "concerns": ["Nile water security", "Inflation and the pound", "Suez Canal revenue",
                     "Gaza border", "Instability in Libya and Sudan", "External debt"],
        "responses": ["Issue a presidential statement", "Coordinate with Gulf and Western partners",
                      "Direct the government to adjust policy", "Raise it in diplomatic talks"],
    },
    {
        "id": "mbs", "name": "Mohammed bin Salman",
        "role": "Crown Prince and Prime Minister of Saudi Arabia", "scope": "Saudi Arabia",
        "personality": "Drives rapid, top-down economic and social modernisation under "
                       "Vision 2030; assertive about Saudi regional leadership.",
        "values": ["Vision 2030 diversification", "Saudi regional leadership", "Security",
                   "Investment"],
        "supports": ["Economic diversification away from oil", "Foreign direct investment",
                     "Tourism and giga-projects", "Regional de-escalation",
                     "Palestinian statehood before normalisation with Israel",
                     "OPEC+ production coordination"],
        "opposes": ["Iranian regional expansion", "Armed militias outside state control",
                    "Foreign criticism of Saudi internal affairs", "Oil price collapse"],
        "concerns": ["Oil prices", "Red Sea and Gulf shipping", "Iran", "Yemen",
                     "Investment climate", "Gaza"],
        "responses": ["Announce investment or aid packages", "Convene a regional summit",
                      "Use oil policy through OPEC+", "Mediate through diplomatic channels"],
    },
    {
        "id": "mbz", "name": "Mohamed bin Zayed", "role": "President of the United Arab Emirates",
        "scope": "UAE",
        "personality": "Security-focused and pragmatic; builds wide economic and security "
                       "partnerships.",
        "values": ["Stability", "Economic openness", "Security", "Tolerance"],
        "supports": ["Normalisation under the Abraham Accords", "Trade and logistics investment",
                     "Technology and AI investment", "Regional de-escalation",
                     "Countering political Islam"],
        "opposes": ["Muslim Brotherhood and political Islamist groups", "Extremism",
                    "Iranian-backed militias", "Attacks on shipping"],
        "concerns": ["Red Sea and Hormuz shipping", "Sudan", "Yemen", "Iran", "Investment flows"],
        "responses": ["Invest or provide financial support", "Issue a foreign ministry statement",
                      "Quiet diplomacy with partners", "Security cooperation"],
    },
    {
        "id": "tamim", "name": "Tamim bin Hamad Al Thani", "role": "Emir of Qatar",
        "scope": "Qatar",
        "personality": "Positions Qatar as a mediator; an independent foreign policy that "
                       "keeps channels open to many sides.",
        "values": ["Mediation", "Sovereignty", "Humanitarian support", "Energy partnerships"],
        "supports": ["Negotiated ceasefires and mediation", "Humanitarian aid to Gaza",
                     "Palestinian statehood", "LNG export partnerships",
                     "Dialogue with all parties"],
        "opposes": ["Blockades and sanctions on Qatar", "Collective punishment of civilians",
                    "Military escalation", "Violations of Qatari sovereignty"],
        "concerns": ["Gaza", "Gulf security", "LNG markets", "Regional escalation"],
        "responses": ["Offer to mediate", "Host negotiations in Doha", "Fund humanitarian aid",
                      "Issue a foreign ministry statement"],
    },
    {
        "id": "abdullah-ii", "name": "King Abdullah II", "role": "King of Jordan",
        "scope": "Jordan",
        "personality": "A moderate diplomatic voice; stresses Hashemite custodianship of "
                       "Jerusalem's Muslim and Christian holy sites.",
        "values": ["Stability", "Moderation", "Custodianship of Jerusalem's holy sites",
                   "Two-state solution"],
        "supports": ["Two-state solution", "Status quo at Jerusalem holy sites",
                     "Humanitarian aid to Gaza", "Economic aid and investment for Jordan",
                     "Refugee burden-sharing"],
        "opposes": ["Displacement of Palestinians into Jordan", "Annexation of the West Bank",
                    "Changes to the Al-Aqsa status quo", "Extremism"],
        "concerns": ["Refugees", "Water scarcity", "Unemployment", "West Bank", "Border security"],
        "responses": ["Issue a Royal Court statement", "Lobby Western capitals",
                      "Coordinate with Egypt and the Gulf", "Raise it at the UN"],
    },
    {
        "id": "erdogan", "name": "Recep Tayyip Erdoğan", "role": "President of Turkey",
        "scope": "Turkey",
        "personality": "Assertive, populist speaking style; seeks an independent regional "
                       "role for Turkey.",
        "values": ["National sovereignty", "Turkish regional influence",
                   "Religious-conservative identity", "Economic growth"],
        "supports": ["The Palestinian cause", "Turkish defence industry",
                     "Syrian reconstruction and refugee returns",
                     "Mediation between Russia and Ukraine", "Trade expansion"],
        "opposes": ["Kurdish militant groups (PKK/YPG)", "Israeli military operations in Gaza",
                    "Western criticism of Turkey", "Sanctions on Turkey"],
        "concerns": ["Inflation and the lira", "Syrian border", "Refugees", "Energy",
                     "Kurdish autonomy"],
        "responses": ["Give a strong public speech", "Summon or recall ambassadors",
                      "Military or security operation", "Offer mediation"],
    },
    {
        "id": "netanyahu", "name": "Benjamin Netanyahu",
        "role": "Prime Minister of Israel, Likud leader", "scope": "Israel",
        "personality": "Security-first; frames issues around threats to Israel and close "
                       "ties with Washington.",
        "values": ["Israeli security", "Jewish state", "Alliance with the United States",
                   "Deterrence"],
        "supports": ["Military pressure on Hamas and Hezbollah",
                     "Normalisation with Arab states", "Pressure on Iran's nuclear programme",
                     "US-Israel security cooperation", "Settlements in the West Bank"],
        "opposes": ["Palestinian statehood", "Iranian nuclear programme", "Hamas and Hezbollah",
                    "International court action against Israel", "UN criticism of Israel"],
        "concerns": ["Iran", "Gaza", "Hostages", "Coalition politics", "US support"],
        "responses": ["Issue a Prime Minister's Office statement", "Military action",
                      "Lobby Washington", "Reject international resolutions"],
    },
    {
        "id": "pezeshkian", "name": "Masoud Pezeshkian", "role": "President of Iran",
        "scope": "Iran",
        "personality": "Reformist-leaning within the system; publicly favours dialogue, while "
                       "the Supreme Leader has the final say on security policy.",
        "values": ["Sovereignty", "The Islamic Republic", "Economic relief", "Ties with neighbours"],
        "supports": ["Sanctions relief through negotiation", "Better ties with neighbouring states",
                     "The Palestinian cause", "Regional economic cooperation"],
        "opposes": ["US and Israeli military strikes", "Sanctions on Iran",
                    "Western interference", "Arab normalisation with Israel"],
        "concerns": ["Sanctions", "Inflation and the rial", "Security", "Energy shortages"],
        "responses": ["Issue a government statement", "Diplomatic outreach to neighbours",
                      "Defer to the Supreme Leader on security", "Raise it at the UN"],
    },
    {
        "id": "abbas", "name": "Mahmoud Abbas",
        "role": "President of the Palestinian Authority, PLO chairman", "scope": "Palestine",
        "personality": "Committed to diplomacy and international law over armed struggle.",
        "values": ["Palestinian statehood", "International legitimacy", "Non-violent diplomacy",
                   "Authority of the PA"],
        "supports": ["Two-state solution on 1967 lines", "UN recognition of Palestine",
                     "Ceasefire in Gaza", "PA governance of Gaza", "International aid"],
        "opposes": ["Israeli settlements", "Annexation", "Displacement of Palestinians",
                    "Hamas control of Gaza", "Plans to relocate Gazans"],
        "concerns": ["Gaza", "West Bank", "PA finances", "Jerusalem", "Elections"],
        "responses": ["Appeal to the UN and international courts", "Issue a presidential statement",
                      "Seek Arab League support", "Suspend or resume coordination"],
    },
    {
        "id": "sharaa", "name": "Ahmed al-Sharaa", "role": "President of Syria",
        "scope": "Syria",
        "personality": "Leads Syria's post-Assad transition; stresses unity, reconstruction "
                       "and ending Syria's isolation.",
        "values": ["Syrian unity", "Reconstruction", "Sovereignty", "Sanctions relief"],
        "supports": ["Lifting sanctions on Syria", "Reconstruction investment",
                     "Partnership with the Gulf and Turkey", "Return of refugees",
                     "Central government control of territory"],
        "opposes": ["Israeli strikes and incursions in Syria", "Armed groups outside state control",
                    "Partition of Syria", "Iranian and Hezbollah influence in Syria"],
        "concerns": ["Economy", "Security", "Sanctions", "Minority relations",
                     "Israeli presence in the south"],
        "responses": ["Visit regional capitals", "Issue a presidency statement",
                      "Request international support", "Security measures"],
    },
    # ---- Influential Egyptians ----
    {
        "id": "madbouly", "name": "Mostafa Madbouly", "role": "Prime Minister of Egypt",
        "scope": "Egypt",
        "personality": "Technocratic; focused on delivering the economic programme and "
                       "attracting investment.",
        "values": ["Economic reform", "Investment", "Fiscal discipline", "Development"],
        "supports": ["Sale of state assets to private investors", "Foreign direct investment",
                     "The IMF programme", "Infrastructure and new cities", "Export growth"],
        "opposes": ["Rising debt service", "Black-market currency trading",
                    "Delays to investment projects"],
        "concerns": ["Inflation", "Debt", "Foreign currency", "Subsidies", "Prices"],
        "responses": ["Hold a press conference", "Announce cabinet measures",
                      "Adjust subsidies or prices", "Meet investors"],
    },
    {
        "id": "abdelatty", "name": "Badr Abdelatty", "role": "Foreign Minister of Egypt",
        "scope": "Egypt",
        "personality": "Career diplomat; very active in mediation and crisis diplomacy.",
        "values": ["Egyptian national security", "Diplomacy", "Arab solidarity", "Sovereignty"],
        "supports": ["Gaza ceasefire and reconstruction", "Two-state solution",
                     "Political settlements in Sudan and Libya",
                     "A binding agreement on the Nile dam"],
        "opposes": ["Displacement of Palestinians", "Unilateral action on the Nile",
                    "Foreign interference", "Military escalation"],
        "concerns": ["Gaza", "Sudan", "Libya", "Nile water", "Red Sea security"],
        "responses": ["Call foreign counterparts", "Issue a foreign ministry statement",
                      "Host talks in Cairo", "Raise it at the UN or Arab League"],
    },
    {
        "id": "hassan-abdalla", "name": "Hassan Abdalla",
        "role": "Governor of the Central Bank of Egypt", "scope": "Egypt",
        "personality": "Focused on bringing inflation down and keeping a flexible exchange rate.",
        "values": ["Price stability", "Monetary credibility", "Banking stability",
                   "Foreign reserves"],
        "supports": ["Flexible exchange rate", "Inflation targeting",
                     "Foreign currency inflows", "Banking sector reform"],
        "opposes": ["Inflationary spending", "Parallel currency market", "Uncontrolled borrowing"],
        "concerns": ["Inflation", "Exchange rate", "Reserves", "Interest rates", "Capital flows"],
        "responses": ["Change interest rates", "Issue a monetary policy statement",
                      "Act through the banking system", "Tighten or ease credit"],
    },
    {
        "id": "el-tayeb", "name": "Sheikh Ahmed el-Tayeb", "role": "Grand Imam of Al-Azhar",
        "scope": "Egypt",
        "personality": "Moderate religious authority; stresses coexistence and Al-Azhar's "
                       "independence.",
        "values": ["Moderate Islam", "Interfaith coexistence", "Human fraternity", "Justice"],
        "supports": ["Interfaith dialogue", "Humanitarian aid to Gaza", "Palestinian rights",
                     "Religious education", "Peace"],
        "opposes": ["Extremism and terrorism", "Islamophobia", "Attacks on civilians",
                    "Desecration of holy sites"],
        "concerns": ["Extremism", "Gaza", "Jerusalem", "Social values", "Religious discourse"],
        "responses": ["Issue an Al-Azhar statement", "Give religious guidance",
                      "Launch an interfaith initiative", "Call for aid"],
    },
    {
        "id": "tawadros", "name": "Pope Tawadros II",
        "role": "Pope of Alexandria, Coptic Orthodox Church", "scope": "Egypt",
        "personality": "Stresses national unity and Christian–Muslim coexistence; supportive "
                       "of the Egyptian state.",
        "values": ["National unity", "Religious freedom", "The Coptic community", "Peace"],
        "supports": ["Equal citizenship", "Church building rights", "National unity",
                     "Interfaith dialogue", "Peace efforts"],
        "opposes": ["Sectarian violence", "Extremism", "Attacks on churches"],
        "concerns": ["Christian community safety", "Citizenship rights", "Emigration",
                     "Social cohesion"],
        "responses": ["Issue a church statement", "Give a pastoral message",
                      "Meet state officials", "Interfaith visits"],
    },
    {
        "id": "sawiris", "name": "Naguib Sawiris",
        "role": "Businessman and investor, founder of Orascom Telecom", "scope": "Egypt",
        "personality": "Outspoken and pro-market; often comments publicly on economic policy.",
        "values": ["Free markets", "Private sector", "Liberal values", "Investment"],
        "supports": ["Private sector growth", "A smaller state role in business",
                     "Foreign investment", "Tax incentives", "Mining and gold investment"],
        "opposes": ["State-owned companies competing with private business", "Bureaucracy",
                    "Heavy taxation", "Religious conservatism in policy"],
        "concerns": ["Exchange rate", "Investment climate", "Taxes", "Regulation"],
        "responses": ["Comment on TV or social media", "Invest or delay investments",
                      "Lobby the government", "Back business initiatives"],
    },
]

# --- Built-in + user-added panel -------------------------------------------
STAKEHOLDERS: list[dict] = []
PROFILES_PUBLIC: list[dict] = []
REMOVED_BUILTINS: list[dict] = []  # built-ins taken off the panel, for restoring


# Panel groups: heads of international organisations, of state, of government, and
# other actors (national bodies such as a central bank, Al-Azhar or a church go here).
CATEGORIES = ("organization", "state", "government", "other")
_CATEGORY = {
    "sisi": "state", "mbz": "state", "tamim": "state", "abdullah-ii": "state", "erdogan": "state",
    "abbas": "state", "sharaa": "state",
    # Saudi Arabia's crown prince is its prime minister; in Iran the president heads the
    # government and the Supreme Leader is head of state.
    "mbs": "government", "netanyahu": "government", "pezeshkian": "government", "madbouly": "government",
    "hassan-abdalla": "other", "el-tayeb": "other", "tawadros": "other",
    "abdelatty": "other", "sawiris": "other",
}
# A role naming one of these is the head of an international organisation.
_INTERNATIONAL = ("united nations", "u.n.", "un secretary", "secretary-general of the un", "arab league",
                  "league of arab states", "african union", "european commission", "european council",
                  "world bank", "imf", "international monetary fund", "nato", "world health", "who director",
                  "world trade", "opec", "brics", "gulf cooperation council", "gcc", "islamic cooperation",
                  "unrwa", "unicef", "unesco", "unhcr", "wfp", "world food", "international", "interpol",
                  "الأمم المتحدة", "جامعة الدول العربية", "الاتحاد الأفريقي", "البنك الدولي", "صندوق النقد",
                  "منظمة", "الدولي", "الدولية")
_GUESS = (
    ("government", ("prime minister", "premier", "chancellor", "head of government", "رئيس الوزراء", "رئيس الحكومة")),
    ("state", ("president of", "king", "emir", "amir", "sultan", "monarch", "head of state", "crown prince",
               "رئيس جمهورية", "رئيس دولة", "الملك", "الأمير", "السلطان")),
)


def category_of(s: dict) -> str:
    """Which panel group a stakeholder belongs to: set by hand, built-in, or guessed from the role."""
    cat = s.get("category")
    if cat in CATEGORIES:
        return cat
    if s.get("id") in _CATEGORY:
        return _CATEGORY[s["id"]]
    role = (s.get("role") or "").lower()
    # "President of the World Bank" heads an international organisation, not a state.
    if any(w in role for w in _INTERNATIONAL):
        return "organization"
    for cat, words in _GUESS:
        if any(w in role for w in words):
            return cat
    return "other"


def _public(s: dict) -> dict:
    out = {k: s.get(k) for k in ("id", "name", "role", "scope", "personality",
                                 "values", "supports", "opposes", "concerns")}
    out["custom"] = bool(s.get("custom"))
    out["category"] = category_of(s)
    out["edited"] = bool(s.get("edited"))
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
    global STAKEHOLDERS, PROFILES_PUBLIC, REMOVED_BUILTINS, BASELINE_PROFILES
    custom = _store.list()
    hidden = _store.hidden()
    edits = _store.edits()
    STAKEHOLDERS = [_edited(s, edits) for s in [s for s in _BUILTIN if s["id"] not in hidden]
                    + [_view(r) for r in custom]]
    REMOVED_BUILTINS = [{"id": s["id"], "name": s["name"]} for s in _BUILTIN if s["id"] in hidden]
    PROFILES_PUBLIC = [_public(s) for s in STAKEHOLDERS]
    profiles = dict(_BUILTIN_PROFILES)
    for r in custom:
        if r.get("profile"):
            profiles[r["id"]] = r["profile"]
    BASELINE_PROFILES = profiles


# Fields of the panel entry a person may change in the profile; the rest of an edit
# ("profile") changes the compiled background shown in the profile window.
PERSON_FIELDS = ("name", "role", "category", "personality", "values", "supports", "opposes", "concerns", "responses")
PROFILE_FIELDS = ("background", "leadership_style", "personality_type", "memberships", "partners", "frictions")


def _edited(s: dict, edits: dict) -> dict:
    e = edits.get(s["id"])
    if not e:
        return s
    return {**s, **{k: v for k, v in e.items() if k in PERSON_FIELDS}, "edited": True}


def localized(s: dict, language: str = "en") -> dict:
    """The panel entry in the interface language: Arabic text for built-in people,
    except for fields someone edited by hand (those keep what was typed)."""
    if language != "ar":
        return s
    from .stakeholders_ar import AR, PERSON_FIELDS as AR_FIELDS
    ar = AR.get(s["id"])
    if not ar:
        return s
    edited = set((_store.edits().get(s["id"]) or {}).keys())
    return {**s, **{k: ar[k] for k in AR_FIELDS if k in ar and k not in edited}}


def public_list(language: str = "en") -> list[dict]:
    return [_public(localized(s, language)) for s in STAKEHOLDERS]


def profile_edit(sid: str) -> dict:
    """The profile fields changed by hand for this person (background, style, alliances...)."""
    return (_store.edits().get(sid) or {}).get("profile") or {}


def edit_stakeholder(sid: str, data: dict) -> dict:
    """Save changes to a person's panel entry and profile; returns their panel entry."""
    if not any(s["id"] == sid for s in STAKEHOLDERS):
        raise KeyError(sid)
    current = dict(_store.edits().get(sid) or {})
    for k in PERSON_FIELDS:
        if k in data and data[k] is not None:
            v = data[k]
            if k in ("values", "supports", "opposes", "concerns", "responses"):
                v = _as_list(v)
            elif k == "category":
                v = v if v in CATEGORIES else None
            else:
                v = str(v).strip()
            if k == "name" and not v:
                continue
            current[k] = v
    prof = dict(current.get("profile") or {})
    for k in PROFILE_FIELDS:
        if k in (data.get("profile") or {}):
            v = data["profile"][k]
            prof[k] = _as_list(v) if k in ("personality_type", "memberships", "partners", "frictions") else str(v or "").strip()
    if prof:
        current["profile"] = prof
    _store.set_edit(sid, current)
    _rebuild()
    return _public(next(s for s in STAKEHOLDERS if s["id"] == sid))


def reset_stakeholder(sid: str) -> None:
    """Drop every change made in the profile: back to the original."""
    _store.set_edit(sid, None)
    _rebuild()


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
    names = {s["id"]: s["name"] for s in _BUILTIN + STAKEHOLDERS}
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
    # Removed built-ins keep their id: they can be restored, and their profile stays bundled.
    taken = {s["id"] for s in _BUILTIN + STAKEHOLDERS}
    sid, n = base_id, 2
    while sid in taken:
        sid, n = f"{base_id}-{n}", n + 1

    record = {
        "id": sid, "name": name, "custom": True,
        "role": (data.get("role") or "").strip(),
        "category": data.get("category") if data.get("category") in CATEGORIES else None,
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
    """Take a stakeholder off the panel: built-ins can be restored, user-added ones are gone."""
    if any(s["id"] == sid for s in _BUILTIN):
        if not any(s["id"] == sid for s in STAKEHOLDERS):
            return False
        _store.set_hidden(sid, True)
    elif not _store.delete(sid):
        return False
    _rebuild()
    return True


def restore_stakeholder(sid: str) -> bool:
    """Put a removed built-in back on the panel."""
    if not any(s["id"] == sid for s in REMOVED_BUILTINS):
        return False
    _store.set_hidden(sid, False)
    _rebuild()
    return True


# --- Word-scorer profile from a stakeholder's own speeches --------------------
_MIN_SPEECH_WORDS = 50
_profile_cache: dict[str, dict] = {}


def speeches_of(sid: str) -> list[dict]:
    """Every speech on file for a stakeholder: the bundled baseline, the one entered
    when a custom stakeholder was added, and any saved from their profile."""
    out = []
    f = _BASELINE_DIR / f"{sid}.txt"
    if f.exists():
        out.append({"id": "file", "title": f.name, "text": f.read_text(encoding="utf-8"),
                    "removable": False})
    for r in _store.list():
        if r.get("id") == sid and r.get("speech"):
            out.append({"id": "custom", "title": "Baseline speech", "text": r["speech"],
                        "removable": False})
    out += [{**r, "removable": True} for r in _store.speeches(sid)]
    return out


def add_speech(sid: str, text: str, title: str = "", context: dict | None = None) -> dict:
    """Save a speech to this person's file. `context` holds the context-check
    decisions made on exactly this text, so they apply again whenever it is scored."""
    text = (text or "").strip()
    if len(text.split()) < _MIN_SPEECH_WORDS:
        raise ValueError(f"A speech needs at least {_MIN_SPEECH_WORDS} words.")
    import time as _t
    import uuid
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    record = {"id": uuid.uuid4().hex[:12], "title": (title or first)[:120].strip(),
              "text": text, "added": _t.strftime("%Y-%m-%d")}
    if context:
        record["context"] = context
    _store.add_speech(sid, record)
    return word_profile(sid)


def delete_speech(sid: str, speech_id: str) -> bool:
    return _store.delete_speech(sid, speech_id)


def _key_of(speeches: list[dict]) -> str:
    return str(hash(json.dumps([[s["text"], s.get("context")] for s in speeches],
                               sort_keys=True, ensure_ascii=False)))


def word_profile(sid: str) -> dict:
    """The word scorer run on everything this person said that is on file, one result
    per language (Arabic and English are scored against their own norms). Context-check
    decisions saved with a speech are applied."""
    from .arabic import is_arabic
    from .context import raw_lta
    from .score import band_lta, merge_lta
    speeches = speeches_of(sid)
    listed = [{"id": s["id"], "title": s.get("title") or "", "words": len(s["text"].split()),
               "language": "ar" if is_arabic(s["text"]) else "en", "added": s.get("added"),
               "removable": s["removable"], "reviewed": bool(s.get("context"))} for s in speeches]
    results = []
    for lang in ("en", "ar"):
        group = [s for s, l in zip(speeches, listed) if l["language"] == lang]
        if not group:
            continue
        key = f"{lang}:{_key_of(group)}"
        if key not in _profile_cache:
            r = band_lta(merge_lta([raw_lta(s["text"], s.get("context")) for s in group]))
            _profile_cache[key] = {
                "language": lang, "speeches": len(group), "tokens": r["tokens"],
                "reviewed": sum(1 for s in group if s.get("context")),
                "traits": {t: {"band": v["band"], "percent": round(v.get("percent", 0.0), 1),
                               "confidence": v.get("confidence")} for t, v in r["traits"].items()},
            }
        results.append(_profile_cache[key])
    return {"speeches": listed, "results": results}


_entity_cache: dict[str, list] = {}


def entity_profile(sid: str) -> list[dict]:
    """The countries and organizations this person names in the speeches on file,
    each with the sentences and a tone per sentence (from the saved context check
    where there is one, else from cue words). Most-named first."""
    from . import entities
    from .context import tone_map
    speeches = speeches_of(sid)
    key = _key_of(speeches)
    if key in _entity_cache:
        return _entity_cache[key]
    merged: dict[str, dict] = {}
    for sp in speeches:
        for e in entities.summarize(sp["text"], tone_map(sp.get("context"))):
            m = merged.setdefault(e["key"], {**entities.info(e["key"]), "count": 0, "statements": []})
            m["count"] += e["count"]
            m["statements"] += [{**st, "speech": sp.get("title") or "", "added": sp.get("added")}
                                for st in e["statements"]]
    out = []
    for m in merged.values():
        m["counts"] = {t: sum(1 for st in m["statements"] if st["tone"] == t)
                       for t in ("positive", "negative", "mixed", "neutral")}
        m["tone"] = entities.overall_tone(m["counts"])
        out.append(m)
    out.sort(key=lambda m: -m["count"])
    if len(_entity_cache) > 64:
        _entity_cache.clear()
    _entity_cache[key] = out
    return out


def views_on(sid: str, keys: list[str], language: str = "en") -> list[dict]:
    """What this person thinks of each country/organization in `keys`: from their own
    speeches on file first, else from their profile's partners and rivals."""
    from . import dossier, entities
    said = {e["key"]: e for e in entity_profile(sid)}
    prof = {**(dossier.PROFILES.get(sid) or {}), **profile_edit(sid)}
    if language == "ar" and not ({"partners", "frictions"} & set(profile_edit(sid))):
        from .stakeholders_ar import AR
        ar = AR.get(sid) or {}
        # Same order as the English, so each Arabic label keeps its country.
        notes = {lbl: a for k in ("partners", "frictions")
                 for lbl, a in zip(prof.get(k, []), ar.get(k, []))}
    else:
        notes = {}
    side = {}
    for label in prof.get("partners", []):
        if (k := dossier.country_of(label)):
            side.setdefault(k, ("positive", label))
    for label in prof.get("frictions", []):
        if (k := dossier.country_of(label)):
            side.setdefault(k, ("negative", label))
    out = []
    for k in keys:
        if k in said:
            e = said[k]
            out.append({**entities.info(k), "tone": e["tone"], "counts": e["counts"],
                        "statements": len(e["statements"]), "source": "speeches"})
        elif k in side:
            out.append({**entities.info(k), "tone": side[k][0], "source": "profile",
                        "note": notes.get(side[k][1], side[k][1])})
    return out


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


def _heuristic_one(text_lc: str, s: dict, language: str = "en") -> dict:
    sup = _matched(text_lc, s["supports"])
    opp = _matched(text_lc, s["opposes"])
    if language == "ar":
        return _heuristic_ar(s, sup, opp)

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


def _heuristic_ar(s: dict, sup: list[str], opp: list[str]) -> dict:
    """The keyword result worded in Arabic: matched items swapped for their Arabic text."""
    loc = localized(s, "ar")
    pick = lambda found, key: [loc[key][s[key].index(x)] if s[key].index(x) < len(loc[key]) else x for x in found]
    sup_ar, opp_ar = pick(sup, "supports"), pick(opp, "opposes")
    join = lambda items: items[0] if len(items) == 1 else "، ".join(items[:-1]) + " و" + items[-1]
    if sup and opp:
        stance, conf = "Mixed", min(85, 55 + 8 * (len(sup) + len(opp)))
        reasoning = f"يُرجَّح أن يرحب بـ{join(sup_ar)}، لكنه يتحفظ على {join(opp_ar)}."
    elif sup:
        stance, conf = "Support", min(92, 55 + 12 * len(sup))
        reasoning = f"يمس قضايا يؤيدها: {join(sup_ar)}."
    elif opp:
        stance, conf = "Oppose", min(92, 55 + 12 * len(opp))
        reasoning = f"يمس أمورًا يعارضها: {join(opp_ar)}."
    else:
        stance, conf = "Neutral", 35
        reasoning = "لا يتناول النص بوضوح الاهتمامات الأساسية لصاحب المصلحة هذا."
    return {"id": s["id"], "name": loc["name"], "role": loc["role"], "stance": stance,
            "confidence": conf, "reasoning": reasoning, "response": loc["responses"][0]}


def _join(items: list[str]) -> str:
    items = [i.lower() for i in items]
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def heuristic_react(text: str, language: str = "en") -> dict:
    text_lc = " " + text.lower() + " "
    return {
        "reactions": [_heuristic_one(text_lc, s, language) for s in STAKEHOLDERS],
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

The stakeholders are real public figures. Ground each judgment in their documented public
positions; never invent quotes, private views or events.

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


_NOTES_PROMPT = """You are reading part {i} of {n} of a long political speech or \
document. Another analyst will use your notes, together with the notes on every \
other part, to predict how political leaders and public figures react to the WHOLE \
document. Note, in order: every position, promise, threat, policy or decision; \
every country, group or person mentioned and how they are described; and the tone. \
Quote the speaker's most important phrases exactly. Write in English, at most 300 \
words. Respond ONLY with JSON: {"notes": "..."}"""


def _notes_on_part(part: str, i: int, n: int, model: str | None) -> str:
    prompt = _NOTES_PROMPT.replace("{i}", str(i + 1)).replace("{n}", str(n))
    for attempt in range(4):
        try:
            data, _ = chat_json([{"role": "system", "content": prompt},
                                 {"role": "user", "content": part}],
                                temperature=0.2, model=model, reasoning_effort="low",
                                max_wait=60.0)
            return str(data.get("notes", "")).strip()
        except httpx.HTTPStatusError as exc:
            # Free tiers allow a few thousand tokens a minute: wait and go again.
            if exc.response.status_code != 429 or attempt == 3:
                raise
            time.sleep(20 * (attempt + 1))
    return ""


def read_in_parts(text: str) -> list[str]:
    """Notes on every part of a long document, in order.

    Parts go to the fallback models, each with its own per-minute quota, so the
    main model stays free for the final judgement.
    """
    parts = split_parts(text)
    models = FALLBACK_MODELS or [None]
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        return list(pool.map(lambda i: _notes_on_part(parts[i], i, len(parts), models[i % len(models)]),
                             range(len(parts))))


def llm_react(text: str, language: str = "en", timeout: float | None = None) -> dict:
    system = _SYSTEM_PROMPT + input_note(text)[1] + _language_instruction(language)
    profiles = f"Stakeholders:\n{_profiles_for_prompt()}\n\n"
    sent, excerpt_note, excerpted = fit_speech(text, system + profiles)
    parts_read = None
    if excerpted:
        # Too long for one call: read every part, then judge from the notes.
        try:
            notes = read_in_parts(text)
            joined = "\n\n".join(f"[Part {i + 1} of {len(notes)}]\n{n}" for i, n in enumerate(notes))
            total = len(text.split())
            sent, excerpt_note, excerpted = fit_speech(joined, system + profiles)
            excerpt_note = (f"\n\nThe document is {total} words long, too long to send whole. "
                            f"It was read in {len(notes)} consecutive parts and you are given notes "
                            "on every part, in order. Judge the whole document from them."
                            + excerpt_note)
            if excerpted:  # so many parts that even the notes had to be sampled
                excerpted = {"read_words": int(total * excerpted["read_words"] / excerpted["total_words"]),
                             "total_words": total}
            parts_read = {"parts": len(notes), "total_words": total}
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"[stakeholders] reading in parts failed, using excerpts: {exc}")
    user = f"{profiles}Speech / policy text:\n\n{sent}"
    # Low reasoning effort: this prompt is ~5.5k tokens, and gpt-oss's hidden
    # reasoning otherwise pushes the call near the free tier's 8k/minute cap.
    data, model = chat_json([
        {"role": "system", "content": system + excerpt_note},
        {"role": "user", "content": user},
    ], temperature=0.3, timeout=timeout, reasoning_effort="low", max_wait=60.0)

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
            "calibrated": any(s["id"] in BASELINE_PROFILES for s in STAKEHOLDERS),
            "excerpted": excerpted, "read_in_parts": parts_read}


def react(text: str, language: str = "en") -> dict:
    """Predict stakeholder reactions, LLM if configured else heuristic."""
    if not STAKEHOLDERS:
        return {"reactions": [], "method": "none"}
    reason = not_configured_reason()
    if available():
        try:
            return llm_react(text, language=language)
        except (httpx.HTTPError, LLMNotConfigured, json.JSONDecodeError,
                KeyError, TypeError, ValueError) as exc:
            # Fall back rather than fail the request -- but say why.
            reason = (not_running_reason() if isinstance(exc, httpx.ConnectError)
                      else "AI provider rate limit reached (HTTP 429)" if
                      isinstance(exc, httpx.HTTPStatusError)
                      and exc.response.status_code == 429
                      else f"{type(exc).__name__}: {exc}")[:300]
            print(f"[stakeholders] AI reactions failed, using keyword fallback: {reason}")
    result = heuristic_react(text, language)
    result["fallback_reason"] = reason
    return result
