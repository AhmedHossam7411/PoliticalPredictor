"""In-group bias in context: who "we" are in each sentence, and what the speaker says about them.

The LTA word list for in-group bias (IGB, predictor.lta) counts words such as
"nation", "citizens" and "foreign" wherever they appear. It cannot tell which group
the speaker means, or whether a sentence shows bias or only belonging. This module
reads every sentence that uses collective language (we, us, our; نحن، ـنا) and:

1. **Finds the group meant** (the referent) from the evidence in and around the
   sentence. Candidate groups come from the speaker's records, never from examples:
   - their country and government (stakeholder role and home country);
   - every organisation in their recorded memberships, and any organisation named in
     their role ("Secretary-General of ...");
   - organisations the speech names (marked "no recorded affiliation");
   - broad collectives the speech names: a continent, the Arab or Islamic world, the
     Global South, the international community.
   The evidence is weighted (see CUE WEIGHTS below): the noun after "our"
   ("our sovereignty" points to the nation, "our cooperation" to a multinational
   group), an apposition ("we, the members of BRICS", "we Africans"), a group named in
   the sentence, the organisation named in the last two sentences, and the speech's
   setting (metadata, or the opening lines: "Excellencies", "this summit"). The
   setting only says *which* organisation a multinational cue points to; it never
   assigns a sentence on its own. Without enough evidence the referent is
   "ambiguous", never a guess.

2. **Separates the speaker's own voice** from quotations ("..."), reported speech
   ("he said that ..."), negation ("we do not believe our interests come first"),
   conditionals and hypotheticals ("if we were ..."), questions and "so-called"
   irony. Those sentences are listed but not counted as evidence.

3. **Classifies each own-voice sentence** into five categories (several may apply):
       identification   belonging, shared identity, common purpose (NOT bias)
       preference       the group's interests put before other groups'
       superiority      the group shown as better, more legitimate or more deserving
       differentiation  "we ... whereas they ...": a line drawn against another group
       hostility        another group shown as a threat, enemy, inferior or excluded
   The last four are the bias indicators. Rules use spaCy's grammatical parse for
   English (who is the subject, what "our" owns, what an adjective describes, what is
   negated or reported); Arabic uses word cues only (no parser).

4. **Scores each group separately** with a transparent rule:
       bias share = sentences about the group with >= 1 bias indicator
                    / all own-voice sentences about the group
   The unit (references to the speaker's own group) follows Hermann's IGB coding
   unit; the five categories, cue lists and thresholds are CORTEX's own
   operationalisation, NOT validated Hermann LTA measurement, and are labelled so in
   the output. Fewer than MIN_REFS sentences -> "Insufficient evidence".
   The overall figure pools every resolved group (method in the output); groups are
   never averaged together silently.

The local AI (Karnak) can be asked to check the ambiguous and borderline sentences
(`ai_check`). Its answers are decisions on the referent, voice and categories of a
numbered sentence, restricted to the candidate list and the fixed codes; the same
deterministic scorer then recomputes. A person can make the same decisions in the
panel. Every decision keeps its source ("rules", "ai", "person").
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from . import arabic, entities

# --------------------------------------------------------------------------- #
# Method constants (shown in the output)
# --------------------------------------------------------------------------- #
MIN_REFS = 5                 # own-voice sentences about a group before it is assessed
LOW_BELOW, HIGH_FROM = 0.10, 0.25   # bias share bands (CORTEX provisional, not normed)
CATEGORIES = ("identification", "preference", "superiority", "differentiation", "hostility")
BIAS = CATEGORIES[1:]
VOICES = ("own", "quoted", "reported", "negated", "hypothetical", "question", "irony")
METHOD = {
    "unit": "Sentences in the speaker's own voice whose collective language (we/us/our) refers to the group.",
    "formula": "bias share = sentences with at least one bias indicator (preference, superiority, "
               "differentiation, hostility) / all own-voice sentences about the group",
    "bands": f"Low below {int(LOW_BELOW * 100)}%, Moderate {int(LOW_BELOW * 100)}-{int(HIGH_FROM * 100)}%, "
             f"High from {int(HIGH_FROM * 100)}% (CORTEX provisional thresholds, not normed against a corpus)",
    "minimum": f"At least {MIN_REFS} own-voice sentences about a group; fewer gives 'Insufficient evidence'.",
    "overall": "All resolved groups pooled: total bias sentences / total own-voice sentences. Ambiguous "
               "references and unnamed partnerships are left out of both counts.",
    "excluded": "Quoted and reported sentences (someone else's words or view) are listed but not counted. "
                "Hypothetical, question and 'so-called' sentences count as references to the group but not as "
                "bias; a negated bias cue ('we do not put our interests first') is set aside and shown.",
    "status": "CORTEX operationalisation (researcher-developed). Not a validated Hermann LTA measurement; "
              "the word-list IGB trait is unchanged and reported separately.",
}

# --------------------------------------------------------------------------- #
# CUE WEIGHTS: what the noun after "our" (or near "we") says about the group
# --------------------------------------------------------------------------- #
# target -> {lemma: weight}. 3 = decisive, 2 = good evidence, 1 = weak (needs support).
# Targets: nation, government, party, military, org (an organisation in context),
# multi (a multinational group in context), continent, region, world, faith.
_NOUN_CUES: dict[str, dict[str, int]] = {
    "nation": {**dict.fromkeys(("country", "nation", "homeland", "motherland", "fatherland", "sovereignty",
                                "border", "territory", "soil", "citizen", "compatriot", "countryman",
                                "countrywoman", "independence", "constitution", "flag"), 3),
               **dict.fromkeys(("people", "land", "economy", "city", "village", "youth", "farmer", "worker",
                                "history", "heritage", "culture", "identity", "tradition", "ancestor",
                                "martyr", "capital", "parliament", "state", "republic", "kingdom",
                                "population", "army"), 2)},
    "government": {**dict.fromkeys(("government", "administration", "cabinet", "ministry"), 3),
                   **dict.fromkeys(("policy", "programme", "program", "reform", "budget"), 1)},
    "party": dict.fromkeys(("party", "movement", "supporter", "voter", "comrade"), 3),
    "military": {**dict.fromkeys(("troop", "soldier", "military", "officer", "fighter", "mujahid",
                                  "brigade"), 3), "force": 2},
    "org": {**dict.fromkeys(("organisation", "organization", "union", "alliance", "bloc", "coalition",
                             "league", "grouping", "membership", "charter", "secretariat", "summit"), 3),
            **dict.fromkeys(("council", "forum", "group", "institution", "assembly"), 2),
            **dict.fromkeys(("presidency", "chairmanship", "mandate", "community"), 1)},
    "multi": {**dict.fromkeys(("cooperation", "partnership", "collaboration", "integration", "consensus",
                               "partner", "member"), 2),
              **dict.fromkeys(("solidarity", "unity", "friendship", "relation", "tie", "dialogue",
                               "agenda", "summit"), 1)},
    "continent": {"continent": 3},
    "region": dict.fromkeys(("region", "neighbourhood", "neighborhood", "subregion"), 2),
    "world": {**dict.fromkeys(("planet", "humanity", "mankind", "species"), 3),
              **dict.fromkeys(("world", "civilization", "civilisation"), 1)},
    "faith": {**dict.fromkeys(("faith", "religion", "ummah", "umma", "church", "creed", "prophet"), 3),
              **dict.fromkeys(("god", "lord", "belief"), 2)},
}
# Adjectives on the noun after "our" (or anywhere on the noun "our" owns).
_MOD_CUES = {"shared": ("multi", 2), "common": ("multi", 2), "collective": ("multi", 2),
             "joint": ("multi", 2), "mutual": ("multi", 2), "national": ("nation", 3),
             "domestic": ("nation", 2), "international": ("world", 2), "global": ("world", 2),
             "regional": ("region", 2), "continental": ("continent", 2), "bilateral": ("multi", 2),
             "multilateral": ("multi", 2)}
# Words anywhere in the sentence (weak, never decisive alone).
_SENT_CUES = {"member states": ("multi", 2), "all nations": ("world", 2), "international community": ("world", 3),
              "together": ("multi", 1), "collectively": ("multi", 1), "jointly": ("multi", 1)}

# Broad collectives a speech can name. key -> (name, name_ar, en patterns, ar patterns, entity key)
_COLLECTIVES = {
    "C-AF": ("Africa", "أفريقيا", [r"\bAfrica\b", r"\bAfricans?\b"], ["افريقيا", "افريقي", "الافارقه", "القاره السمراء"], "C-AF"),
    "C-EU": ("Europe", "أوروبا", [r"\bEurope\b", r"\bEuropeans?\b"], ["اوروبا", "اوروبي"], "C-EU"),
    "C-AS": ("Asia", "آسيا", [r"\bAsia\b", r"\bAsians?\b"], ["اسيا", "اسيوي"], "C-AS"),
    "C-LA": ("Latin America", "أمريكا اللاتينية", [r"\bLatin America\w*\b"], ["امريكا اللاتينيه"], "C-LA"),
    "ARAB": ("The Arab world", "العالم العربي", [r"\bArab (?:world|nation|peoples?|countries|states)\b", r"\bArabs\b"],
             ["العالم العربي", "الامه العربيه", "الدول العربيه", "الشعوب العربيه", "العرب"], None),
    "ISLAM": ("The Islamic world / Muslim community", "العالم الإسلامي",
              [r"\b(?:Islamic|Muslim) (?:world|nations?|ummah|umma|community|countries)\b", r"\bMuslims\b", r"\bummah?\b"],
              ["العالم الاسلامي", "الامه الاسلاميه", "المسلمين", "المسلمون"], None),
    "SOUTH": ("The Global South", "الجنوب العالمي",
              [r"\bGlobal South\b", r"\bdeveloping (?:countries|nations|world)\b", r"\bthird world\b"],
              ["الجنوب العالمي", "الدول الناميه", "دول الجنوب"], None),
    "INTL": ("The international community", "المجتمع الدولي",
             [r"\binternational community\b", r"\bhumanity\b", r"\bmankind\b", r"\ball nations\b", r"\bthe world\b"],
             ["المجتمع الدولي", "الانسانيه", "البشريه", "العالم"], None),
}
_CONTINENT_KEYS = ("C-AF", "C-EU", "C-AS", "C-LA")
# Continental organisations: "our continent" in a speech by a member means this continent.
_CONTINENT_OF_ORG = {"AU": "C-AF", "EU": "C-EU"}

# Group-type words in a role or a membership line.
_HEAD_RE = re.compile(r"\b(president|prime minister|premier|chancellor|king|queen|emir|amir|sultan|crown prince|"
                      r"head of (?:state|government)|supreme leader|taoiseach)\b", re.I)
_GOV_MEMBER_RE = re.compile(r"\b(minister|secretary of state|spokes\w+|ambassador|envoy|governor)\b", re.I)
_MIL_RE = re.compile(r"\b(army|armed forces|military|general|commander|marshal|forces|militia|brigades?)\b", re.I)
_PARTY_RE = re.compile(r"\b(party|movement|front)\b", re.I)

# --------------------------------------------------------------------------- #
# Category cues
# --------------------------------------------------------------------------- #
_PREF_RES = [re.compile(p, re.I) for p in (
    r"\b(?:come|comes|coming|came|put|puts|putting|place|places|placing|be|is|are|remain|remains)\s+(?:\w+\s+){0,3}?first\b",
    r"\b(?:take|takes|taking|took|have|has|get|gets|given?)\s+(?:\w+\s+)?(?:priority|precedence|primacy|preference)\b",
    r"\b(?:priority|precedence|primacy|preference)\s+(?:over|to)\b",
    r"\b(?:before|above|ahead of|over)\s+(?:those|that|the\s+(?:interests?|needs|rights|welfare|concerns))\s+of\s+(?:all\s+)?(?:other|foreign|another|any other|others)",
    r"\b(?:before|above|over)\s+(?:all\s+)?(?:other|foreign)\s+(?:countries|nations|peoples|states|people)\b",
    r"\bat the expense of\b",
    r"\b(?:rather than|instead of|not)\s+(?:for\s+)?(?:foreigners|outsiders|immigrants|other (?:countries|nations|peoples))\b",
    r"\b(?:our|we)\b.{0,40}\b(?:alone|only)\b.{0,20}\b(?:deserve|matter|count)",
    r"\b(?:favour|favor|prefer|privilege)(?:s|ed|ing)?\s+(?:our|us)\b",
    r"\b[A-Z][a-z]+ first\b",
)]
_SUPERIOR_WORDS = {"superior", "exceptional", "unrivalled", "unrivaled", "unmatched", "unparalleled", "chosen",
                   "indispensable"}
_SUPERIOR_RES = [re.compile(p, re.I) for p in (
    r"\blike no other\b", r"\bsecond to none\b", r"\bnone (?:can|could) (?:match|equal|rival)\b",
    r"\bmore (?:deserving|legitimate|civili[sz]ed|worthy|capable|advanced|noble)\b",
    r"\benvy of the world\b", r"\b(?:greatest|best|strongest|finest|noblest|bravest|mightiest) (?:\w+ )?(?:in|on) (?:the )?(?:world|earth|history|planet)\b",
    r"\bno (?:other )?(?:nation|country|people|state) (?:is|can be|has ever been) (?:greater|better|stronger|braver|nobler)\b",
)]
# Evaluative adjectives that make a comparison a claim of superiority (not a fact
# such as "the largest economy").
_EVALUATIVE = {"great", "good", "strong", "powerful", "fine", "noble", "brave", "smart", "wise", "civilized",
               "civilised", "advanced", "capable", "legitimate", "worthy", "deserving", "mighty", "glorious",
               "proud", "righteous", "pure", "honest", "superior", "exceptional"}
_CONTRAST = {"whereas", "while", "unlike", "but", "however", "instead", "rather"}
_CONTRAST_RES = [re.compile(p, re.I) for p in (
    r"\bus (?:and|versus|vs\.?|against) them\b", r"\bwith us or against us\b", r"\bnot like (?:them|us)\b",
    r"\bin contrast\b", r"\bon the other hand\b", r"\bunlike (?:them|those|others|our (?:enemies|adversaries|rivals))\b",
)]
_HOSTILE_NOUNS = {"enemy", "foe", "invader", "traitor", "terrorist", "aggressor", "occupier", "infiltrator",
                  "parasite", "vermin", "savage", "barbarian", "conspirator", "colonizer", "coloniser",
                  "intruder", "oppressor", "criminal", "thug", "agent", "mercenary", "usurper"}
_HOSTILE_ADJ = {"illegitimate", "inferior", "barbaric", "savage", "hostile", "treacherous", "evil", "criminal",
                "subhuman", "undeserving", "backward", "uncivilized", "uncivilised", "dangerous", "aggressive",
                "malicious", "wicked", "corrupt", "fanatic", "fanatical"}
_HOSTILE_VERBS = {"threaten", "invade", "betray", "conspire", "plot", "infiltrate", "destroy", "occupy",
                  "attack", "subjugate", "exploit", "loot", "plunder", "humiliate"}
_EXCLUDE_RES = [re.compile(p, re.I) for p in (
    r"\b(?:do|does|did) not belong\b", r"\bhave no place\b", r"\bnot (?:one of us|welcome)\b",
    r"\b(?:expel|deport|throw out|keep out|drive out|kick out)\b", r"\bgo back (?:to|where)\b",
    r"\bundeserving\b", r"\bno right to (?:be|live|stay)\b",
)]
_OUT_NOUNS = {"foreigner", "outsider", "alien", "immigrant", "migrant", "other", "opponent", "adversary",
              "rival", "west", "colonizer", "coloniser", "enemy", "foe", "invader", "occupier"}
_OUT_PRON = {"they", "them", "their", "theirs", "themselves"}
_SELF_PLURAL = {"we", "us", "our", "ours", "ourselves"}
_SELF_SING = {"i", "me", "my", "myself", "mine"}
_REPORT_VERBS = {"say", "claim", "argue", "tell", "insist", "declare", "assert", "allege", "write", "state",
                 "suggest", "shout", "chant", "warn", "accuse", "proclaim", "announce", "believe", "think",
                 "pretend"}
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("«", "»"), ("‘", "’"))
_NEG_WORDS = {"not", "n't", "never", "no", "neither", "nor", "cannot", "nobody", "none", "nothing"}
_HYPO_START = re.compile(r"^\s*(?:imagine|suppose|supposing|what if|let us imagine|picture)\b", re.I)

# Speech setting cues (opening lines, metadata).
_MULTI_OPEN = re.compile(
    r"\b(?:Excellenc(?:y|ies)|distinguished delegates|heads of (?:state|delegation)s?(?: and government)?|"
    r"President of the General Assembly|General Assembly|Secretary-General|this (?:august )?(?:assembly|summit|session|"
    r"conference|forum|gathering|ministerial)|fellow (?:leaders|members|heads)|member states|summit)\b", re.I)
_NAT_OPEN = re.compile(
    r"\b(?:(?:my |dear )?fellow (?:citizens|countrymen|compatriots|[A-Z][a-z]+(?:ans|ians|ese|is|ish|ch))|"
    r"dear compatriots|members of (?:the )?(?:parliament|congress|national assembly|house)|"
    r"honou?rable members|address to the nation|state of the (?:union|nation)|people of [A-Z][a-z]+)\b")
_VENUE_WORDS = re.compile(r"\b(?:summit|assembly|session|conference|meeting|council|forum|congress|gathering|"
                          r"ministerial|plenary)\b", re.I)
_AR_MULTI_OPEN = re.compile(r"(?:اصحاب الفخامه|اصحاب السمو|القمه|الجمعيه العامه|الدول الاعضاء|السيد الامين العام|المؤتمر|الدوره)")
_AR_NAT_OPEN = re.compile(r"(?:المواطنين|المواطنون|ايها الشعب|شعب [ء-ي]+ العظيم|الاخوه المواطن|السيدات والساده اعضاء مجلس النواب|مجلس النواب|مجلس الشعب)")


# --------------------------------------------------------------------------- #
# Candidate groups
# --------------------------------------------------------------------------- #
def _group(key: str, kind: str, name: str, name_ar: str, relation: str, source: str,
           recorded: bool, patterns_en=(), patterns_ar=(), entity: str | None = None) -> dict:
    return {"key": key, "kind": kind, "name": name, "name_ar": name_ar or name, "relation": relation,
            "relation_source": source, "recorded": recorded, "entity": entity,
            "patterns_en": list(patterns_en), "patterns_ar": list(patterns_ar)}


def _entity_patterns(key: str) -> tuple[list[str], list[str]]:
    e = entities.ENTITIES[key]
    return ([rf"(?<![\w.]){re.escape(f)}(?!\w)" for f in e["en"]], [arabic.normalize(f) for f in e["ar"]])


def _acronym(name: str) -> str | None:
    words = [w for w in re.findall(r"[A-Za-z][\w-]*", name) if w.lower() not in ("of", "the", "and", "for")]
    if len(words) < 3:
        return None
    return "".join(w[0].upper() for w in words)


def _membership_groups(lines: list[str]) -> list[dict]:
    """One group per recorded membership line; known organisations get their key."""
    out: dict[str, dict] = {}
    for line in lines:
        line = (line or "").strip()
        # "Not a member of the PLO" records a non-affiliation: no group to assess.
        if not line or re.match(r"(?i)^(?:not|no longer|never)\b", line):
            continue
        found = [m["key"] for m in entities.find(line) if entities.ENTITIES[m["key"]]["kind"] == "organization"]
        if found:
            for k in dict.fromkeys(found):
                gkey = f"org:{k}"
                if gkey in out:
                    out[gkey]["relation"] += f"; {line}"
                    continue
                en, ar = _entity_patterns(k)
                info = entities.info(k)
                out[gkey] = _group(gkey, "organization", info["name"], info["name_ar"], line, "recorded membership",
                                   True, en, ar, k)
            continue
        name = re.split(r"[(;]", line)[0].strip(" ,.")
        if not name:
            continue
        gkey = "org:" + re.sub(r"\W+", "-", name.lower()).strip("-")
        pats = [rf"(?<!\w){re.escape(name)}(?!\w)"]
        if (acr := _acronym(name)):
            pats.append(rf"(?<![\w.]){acr}(?!\w)")
        out.setdefault(gkey, _group(gkey, "organization", name, name, line, "recorded membership", True, pats,
                                    [arabic.normalize(name)] if arabic.is_arabic(name) else []))
    return list(out.values())


def candidate_groups(text: str, home: str | None, role: str, affiliations: list[str],
                     setting: dict) -> list[dict]:
    """Every group the speaker's collective language could refer to in this text."""
    role = role or ""
    groups: list[dict] = []
    if home and home in entities.ENTITIES:
        info = entities.info(home)
        en, ar = _entity_patterns(home)
        rel = role if role else "Home country on record"
        groups.append(_group("nation", "nation", info["name"], info["name_ar"], rel,
                             "stakeholder role" if role else "home country", True, en, ar, home))
        gname, gname_ar = f"Government of {info['name']}", f"حكومة {info['name_ar']}"
    else:
        groups.append(_group("nation", "nation", "The speaker's country (not identified)", "دولة المتحدث (غير محددة)",
                             "Not recorded (no speaker chosen)" if not role else role, "none", False))
        gname, gname_ar = "The speaker's government", "حكومة المتحدث"
    if _HEAD_RE.search(role):
        grel, grec = f"Leads it ({role})", True
    elif _GOV_MEMBER_RE.search(role):
        grel, grec = f"Member ({role})", True
    else:
        grel, grec = "Not recorded", False
    groups.append(_group("government", "government", gname, gname_ar, grel, "stakeholder role" if grec else "none", grec))

    # Organisations named in the role: the speaker heads or serves them.
    seen = {"nation", "government"}
    for m in entities.find(role):
        k = m["key"]
        if entities.ENTITIES[k]["kind"] == "organization" and f"org:{k}" not in seen:
            en, ar = _entity_patterns(k)
            info = entities.info(k)
            groups.append(_group(f"org:{k}", "organization", info["name"], info["name_ar"], role, "stakeholder role",
                                 True, en, ar, k))
            seen.add(f"org:{k}")
    for g in _membership_groups(affiliations):
        if g["key"] in seen:
            continue
        groups.append(g)
        seen.add(g["key"])
    groups.append(_group("party", "party", "The speaker's party or movement", "حزب المتحدث أو حركته",
                         role if _PARTY_RE.search(role) else "Not recorded",
                         "stakeholder role" if _PARTY_RE.search(role) else "none", bool(_PARTY_RE.search(role))))
    groups.append(_group("military", "military", "Armed forces / security services", "القوات المسلحة والأجهزة الأمنية",
                         role if _MIL_RE.search(role) else "Not recorded",
                         "stakeholder role" if _MIL_RE.search(role) else "none", bool(_MIL_RE.search(role))))
    # Organisations the speech names or is hosted by, with no recorded membership.
    named = {m["key"] for m in entities.find(text)}
    host = setting.get("host_entity")
    for k in sorted(named | ({host} if host else set())):
        if k in entities.ENTITIES and entities.ENTITIES[k]["kind"] == "organization" and f"org:{k}" not in seen:
            en, ar = _entity_patterns(k)
            info = entities.info(k)
            src = "speech setting" if k == host else "named in the speech"
            groups.append(_group(f"org:{k}", "organization", info["name"], info["name_ar"],
                                 "No recorded affiliation", src, False, en, ar, k))
            seen.add(f"org:{k}")
    for ck, (name, name_ar, pen, par, ent) in _COLLECTIVES.items():
        rel, rec = "No recorded affiliation", False
        if ck in _CONTINENT_KEYS:
            org = next((o for o, c in _CONTINENT_OF_ORG.items() if c == ck and f"org:{o}" in seen
                        and next(g for g in groups if g["key"] == f"org:{o}")["recorded"]), None)
            if org:
                rel, rec = f"Member of the {entities.info(org)['name']} (recorded)", True
        if ck == "ISLAM" and any(g["key"] == "org:OIC" and g["recorded"] for g in groups):
            rel, rec = "Member of the Organisation of Islamic Cooperation (recorded)", True
        if ck == "ARAB" and any(g["key"] == "org:AL" and g["recorded"] for g in groups):
            rel, rec = "Member of the Arab League (recorded)", True
        groups.append(_group(f"col:{ck}", "religious" if ck == "ISLAM" else "collective", name, name_ar, rel,
                             "recorded membership" if rec else "none", rec, pen, par, ent))
    groups.append(_group("religious", "religious", "A religious community (not named)", "جماعة دينية (غير مسماة)",
                         "Not recorded", "none", False))
    groups.append(_group("partnership", "partnership", "A partnership or coalition (not named)",
                         "شراكة أو تحالف (غير مسمى)", "Not identified", "none", False))
    return groups


# --------------------------------------------------------------------------- #
# Speech setting (speech-level context)
# --------------------------------------------------------------------------- #
def _org_in(s: str) -> str | None:
    found = [m["key"] for m in entities.find(s or "") if entities.ENTITIES[m["key"]]["kind"] == "organization"]
    return found[0] if found else None


def detect_setting(text: str, sents: list[tuple[int, int]], metadata: dict | None) -> dict:
    """Where and to whom the speech was given: metadata first, then the opening lines."""
    meta = {k: str(v).strip() for k, v in (metadata or {}).items() if v and str(v).strip()}
    evidence, kind, host, source = [], "unclear", None, None
    declared = " ".join(meta.get(k, "") for k in ("event", "host", "audience", "location", "title"))
    if declared:
        host = _org_in(meta.get("host", "")) or _org_in(meta.get("event", "")) or _org_in(declared)
        if host:
            source = "metadata"
            evidence.append(f"Metadata names {entities.info(host)['name']}")
        if _MULTI_OPEN.search(declared) or host:
            kind = "multilateral"
        elif _NAT_OPEN.search(declared) or re.search(r"\b(?:parliament|national|nation|citizens|rally|"
                                                     r"press conference|domestic)\b", declared, re.I):
            kind = "national"
            evidence.append("Metadata describes a national setting")
    is_ar = arabic.is_arabic(text)
    opening = text[:sents[min(len(sents), 12) - 1][1]] if sents else text[:2000]
    opening = opening[:2500]
    probe = arabic.normalize(opening) if is_ar else opening
    multi = (_AR_MULTI_OPEN if is_ar else _MULTI_OPEN).findall(probe)
    nat = (_AR_NAT_OPEN if is_ar else _NAT_OPEN).findall(probe)
    if kind == "unclear":
        if len(multi) > len(nat):
            kind = "multilateral"
        elif nat:
            kind = "national"
    if multi:
        evidence.append("Opening lines address a multilateral audience (" + ", ".join(sorted(set(multi))[:4]) + ")")
    if nat:
        evidence.append("Opening lines address a national audience (" + ", ".join(sorted(set(nat))[:4]) + ")")
    if not host and kind == "multilateral":
        # The organisation named next to "summit", "session", "assembly" in the opening.
        for s, e in sents[:12]:
            sent = text[s:e]
            if (_VENUE_WORDS.search(sent) or (is_ar and _AR_MULTI_OPEN.search(arabic.normalize(sent)))) and (k := _org_in(sent)):
                host, source = k, "text"
                evidence.append(f"Opening lines name the venue: {entities.info(k)['name']}")
                break
        if not host and re.search(r"General Assembly|الجمعيه العامه", probe):
            host, source = "UN", "text"
    return {"type": kind, "host_entity": host, "host": entities.info(host) if host else None,
            "source": source, "evidence": evidence, "metadata": meta}


# --------------------------------------------------------------------------- #
# Sentences
# --------------------------------------------------------------------------- #
def _sentences(text: str) -> list[tuple[int, int]]:
    from .context import sentences
    return sentences(text)


def _quote_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for a, b in _QUOTE_PAIRS:
        if a == b:
            idx = [m.start() for m in re.finditer(re.escape(a), text)]
            spans += [(idx[i], idx[i + 1]) for i in range(0, len(idx) - 1, 2)]
        else:
            for m in re.finditer(re.escape(a) + r"[^" + re.escape(b) + r"]{1,2000}" + re.escape(b), text):
                spans.append((m.start(), m.end()))
    # Straight single quotes are apostrophes too often to use.
    return spans


def _paragraph_breaks(text: str, sents: list[tuple[int, int]]) -> list[bool]:
    """True where a sentence starts a new paragraph."""
    out = []
    for i, (s, _e) in enumerate(sents):
        prev_end = sents[i - 1][1] if i else 0
        out.append(i == 0 or bool(re.search(r"\n\s*\n", text[prev_end - 2 if prev_end >= 2 else 0:s + 1])))
    return out


def _mentions(groups: list[dict], text: str, s: int, e: int, is_ar: bool) -> dict[str, list[tuple[int, int]]]:
    """Group key -> character spans where the sentence names the group."""
    out: dict[str, list[tuple[int, int]]] = {}
    sent = text[s:e]
    if is_ar:
        norm = arabic.normalize(sent)
        for g in groups:
            for p in g["patterns_ar"]:
                if p and p in norm:
                    out.setdefault(g["key"], []).append((s, e))
                    break
    for g in groups:
        for rx in _compiled(tuple(g["patterns_en"])):
            for m in rx.finditer(sent):
                out.setdefault(g["key"], []).append((s + m.start(), s + m.end()))
    return out


@lru_cache(maxsize=4096)
def _compiled(patterns: tuple) -> tuple:
    return tuple(re.compile(p) for p in patterns)


# --------------------------------------------------------------------------- #
# English: expressions, cues and voice from the parse
# --------------------------------------------------------------------------- #
def _found_in(text: str, s: int, e: int) -> list[dict]:
    """Countries/organisations named in [s, e): one scan of the whole text, cached."""
    return [m for m in _all_found(text) if s <= m["start"] < e]


@lru_cache(maxsize=8)
def _all_found(text: str) -> tuple:
    return tuple(entities.find(text))


def _tokens_in(doc, s: int, e: int) -> list:
    """Tokens of the sentence [s, e) (binary search on the token start offsets)."""
    import bisect
    starts = _token_starts(doc)
    a, b = bisect.bisect_left(starts, s), bisect.bisect_left(starts, e)
    return [doc[k] for k in range(a, b)]


def _token_starts(doc) -> list[int]:
    # Kept on the parsed document itself (an id() key could be reused by a later text).
    if "ingroup_starts" not in doc.user_data:
        doc.user_data["ingroup_starts"] = [t.idx for t in doc]
    return doc.user_data["ingroup_starts"]


def _is_self_plural(t) -> bool:
    return t.lower_ in _SELF_PLURAL and t.text not in ("US", "U.S.", "Us.")


def _possessed(t):
    """For "our": the noun it owns ("our country's interests" -> "country"). For "we" as
    the subject of "be": the noun it is said to be ("we are a proud nation" -> "nation")."""
    if t.dep_ == "poss":
        return t.head
    if t.dep_ == "nsubj" and t.head.lemma_ == "be":
        return next((c for c in t.head.children if c.dep_ == "attr" and c.pos_ in ("NOUN", "PROPN")), None)
    return None


def _noun_cues(noun, owner: str = "our") -> list[tuple[str, int, str]]:
    """(target, weight, why) from the noun "our" owns (or "we are a ..."), and its modifiers."""
    out = []
    lemma = noun.lemma_.lower()
    words = [(lemma, noun.text)]
    words += [(c.lemma_.lower(), c.text) for c in noun.children if c.dep_ == "compound"]
    for lem, surface in words:
        for target, table in _NOUN_CUES.items():
            if lem in table:
                out.append((target, table[lem], f'"{owner} {surface}"'))
    if lemma == "state" and any(c.lower_ == "member" for c in noun.children):
        out.append(("multi", 3, '"our member states"'))
    for c in noun.children:
        mod = c.lemma_.lower() if c.lemma_.lower() in _MOD_CUES else c.lower_
        if c.dep_ in ("amod", "compound") and mod in _MOD_CUES:
            target, w = _MOD_CUES[mod]
            out.append((target, w, f'"{c.text} {noun.text}"'))
    return out


_APPOS_AFTER = re.compile(
    r"^\s*,?\s*(?:all\s+|both\s+)?(?:(?:who\s+are\s+|here\s+)?(?:in|as|from|of)\s+|the\s+)(?:the\s+)?"
    r"(?:(?:members?|leaders?|peoples?|citizens|nations|countries|states|people|governments?)\s+of\s+(?:the\s+)?)?"
    r"(?P<x>[A-Z][\w.'-]*(?:\s+(?:of\s+|the\s+)?[A-Z][\w.'-]*){0,5})")
_DEMONYM_AFTER = re.compile(r"^\s*,?\s*(?:the\s+)?(?:proud\s+)?(?P<x>[A-Z][a-z]+(?:ans|ians|ese|is|ers|ish|ch|s))\b")
_AS_BEFORE = re.compile(r"\b(?:As|as|Here in|here in|In|in)\s+(?:the\s+)?(?:(?:members?|leaders?)\s+of\s+(?:the\s+)?)?"
                        r"(?P<x>[A-Z][\w.'-]*(?:\s+(?:of\s+|the\s+)?[A-Z][\w.'-]*){0,5})\s*,\s*$")
_RELIGIOUS_DEMONYMS = {"muslims": "col:ISLAM", "believers": "religious", "christians": "religious", "jews": "religious"}


def _group_for_name(name: str, groups: list[dict]) -> str | None:
    for g in groups:
        if any(re.search(p, name) for p in g["patterns_en"]):
            return g["key"]
    stem = name.lower()
    if stem in _RELIGIOUS_DEMONYMS:
        return _RELIGIOUS_DEMONYMS[stem]
    for g in groups:
        nm = g["name"].lower().removeprefix("the ")
        if g["kind"] in ("nation", "collective") and len(nm) >= 4 and stem[:min(len(nm), 5)] == nm[:min(len(nm), 5)]:
            return g["key"]
    return None


def _appositive_cues(t, text: str, sent_start: int, groups: list[dict]) -> list[tuple[str, int, str]]:
    """'we, the members of BRICS', 'we Africans', 'As Egypt, we'."""
    if t.lower_ not in ("we", "us"):
        return []
    after = text[t.idx + len(t.text): t.idx + len(t.text) + 90]
    before = text[sent_start: t.idx]
    out = []
    for rx in (_APPOS_AFTER, _DEMONYM_AFTER):
        m = rx.match(after)
        if m and (k := _group_for_name(m.group("x"), groups)):
            out.append((k, 4, f'"{t.text}{after[:m.end()]}"'))
            break
    m = _AS_BEFORE.search(before)
    if m and (k := _group_for_name(m.group("x"), groups)):
        out.append((k, 4, f'"{m.group(0).strip()} {t.text}"'))
    return out


def _clause_head(t):
    """The verb (or predicate) whose clause holds token t."""
    cur = t
    for _ in range(12):
        if cur.pos_ in ("VERB", "AUX") or cur.dep_ in ("ROOT", "ccomp", "advcl", "xcomp", "conj", "relcl"):
            return cur
        if cur.head is cur:
            return cur
        cur = cur.head
    return cur


def _negated(v) -> bool:
    if any(c.dep_ == "neg" or (c.lower_ in _NEG_WORDS and c.dep_ in ("advmod", "aux", "det", "neg")) for c in v.children):
        return True
    # "No country is superior" negates through the subject.
    subj = next((c for c in v.children if c.dep_ in ("nsubj", "nsubjpass")), None)
    return bool(subj and any(c.lower_ in ("no", "none", "neither") and c.dep_ == "det" for c in subj.children))


def _conditional(v) -> bool:
    cur = v
    for _ in range(6):
        if any(c.dep_ == "mark" and c.lower_ in ("if", "unless", "whether") for c in cur.children):
            return True
        if cur.head is cur:
            break
        cur = cur.head
    return False


def _reported(t) -> str | None:
    """'reported' when t sits in what someone else is said to say or think."""
    cur = t
    for _ in range(14):
        h = cur.head
        if h is cur:
            return None
        # Only a clause that is what they say or think ("He said that ...", "They claim we ...").
        if h.lemma_.lower() in _REPORT_VERBS and cur.dep_ in ("ccomp", "parataxis"):
            subj = next((c for c in h.children if c.dep_ in ("nsubj", "nsubjpass")), None)
            if subj is not None and subj.lower_ not in _SELF_PLURAL | _SELF_SING:
                return "reported"
        cur = h
    return None


_OTHERS_VIEW = re.compile(r"\b(?:according to|they say|some say|some claim|those who (?:say|claim|argue|believe)|"
                         r"(?:critics|opponents|enemies|adversaries|detractors) (?:say|claim|argue|believe))\b", re.I)


def _voice(pos: int, t, text: str, sent: tuple[int, int], quotes: list[tuple[int, int]], sent_text: str) -> str:
    """'own', 'quoted' (inside quotation marks) or 'reported' (someone else's view)."""
    if any(a < pos < b for a, b in quotes):
        # A quotation the speaker introduces as their own words ("I said: '...'") stays theirs.
        intro = text[max(0, sent[0] - 200):pos].lower()
        if not re.search(r"\b(?:i|we)\s+(?:said|say|told|tell|declared|declare|repeat|promised)\b[^.]{0,40}$", intro):
            return "quoted"
    if t is not None and _reported(t):
        return "reported"
    if _OTHERS_VIEW.search(sent_text):
        return "reported"
    return "own"


def _modality(t, sent_text: str) -> list[str]:
    """Why the speaker's sentence isn't a plain claim: hypothetical, question, irony."""
    out = []
    if _HYPO_START.search(sent_text) or (t is not None and _conditional(_clause_head(t))):
        out.append("hypothetical")
    if sent_text.rstrip().rstrip('"”»\'').endswith(("?", "؟")):
        out.append("question")
    if re.search(r"\bso-called\b|ما يسمى|ما يسمي", sent_text, re.I):
        out.append("irony")
    return out


def _degree(tok) -> tuple[str, str]:
    """(base adjective, "comparative" | "superlative" | ""). The small English model
    sometimes tags "braver" as an adverb, so the word's ending is read too."""
    w, lem = tok.lower_, tok.lemma_.lower()
    if any(c.lower_ == "more" for c in tok.children):
        return lem, "comparative"
    if any(c.lower_ == "most" for c in tok.children):
        return lem, "superlative"
    if tok.tag_ in ("JJR", "RBR") and lem in _EVALUATIVE:
        return lem, "comparative"
    if tok.tag_ in ("JJS", "RBS") and lem in _EVALUATIVE:
        return lem, "superlative"
    irregular = {"better": ("good", "comparative"), "best": ("good", "superlative")}
    if w in irregular:
        return irregular[w]
    for end, degree in (("iest", "superlative"), ("ier", "comparative"), ("est", "superlative"),
                        ("er", "comparative"), ("st", "superlative"), ("r", "comparative")):
        if w.endswith(end) and len(w) > len(end) + 2:
            stem = w[:-len(end)]
            for cand in (stem, stem + "e", stem + "y", stem[:-1] if len(stem) > 3 and stem[-1] == stem[-2] else stem):
                if cand in _EVALUATIVE:
                    return cand, degree
    return lem, ""


_GROUP_NOUNS = {"nation", "country", "people", "army", "civilization", "civilisation", "state", "race", "culture",
                "religion", "faith", "union", "alliance", "continent", "community"}
_WORLD_FRAME = re.compile(r"\b(?:in|on|of) (?:the )?(?:world|earth|history|planet|all)\b", re.I)
_THAN_OTHERS = re.compile(r"\bthan (?!ever\b|before\b|yesterday\b|we\b|us\b|ours?\b|expected\b|planned\b)", re.I)


def _category_cues(toks: list, sent_text: str, self_toks: list, out_present: bool,
                   sent_start: int) -> tuple[dict[str, list[str]], list[str]]:
    """(category -> reasons, negated cues), from the parse and the cue lists (English).

    A cue whose own clause is negated ("we do not put our interests first", "they are
    not our enemies") is set aside and reported, not counted. Negation elsewhere in the
    sentence ("we will never let our enemies win") does not cancel a label.
    """
    cats: dict[str, list[str]] = {}
    negated: list[str] = []
    low = sent_text.lower()
    tok_at = {t.idx: t for t in toks}

    def tok_near(pos: int):
        return next((t for t in toks if t.idx <= pos < t.idx + len(t.text) + 1), None) or tok_at.get(pos)

    def add(c: str, why: str, tok=None, check_neg: bool = True) -> None:
        if check_neg and tok is not None and _negated(_clause_head(tok)):
            negated.append(f"{c}: {why} (negated)")
            return
        cats.setdefault(c, []).append(why)

    for rx in _PREF_RES:
        m = rx.search(sent_text)
        if m:
            add("preference", f'priority wording: "{m.group(0).strip()}"', tok_near(sent_start + m.start()))
            break
    in_group_heads = {_possessed(t).i for t in self_toks if _possessed(t) is not None}  # positions: spaCy Tokens are new objects each access
    self_ids = {t.i for t in self_toks}

    def about_group(target) -> bool:
        return target is not None and (target.i in self_ids or target.i in in_group_heads
                                       or any(c.i in self_ids for c in target.children))

    for tok in toks:
        lem = tok.lemma_.lower()
        if lem in _SUPERIOR_WORDS and self_toks:
            add("superiority", f'"{tok.text}"', tok)
        if tok.pos_ not in ("ADJ", "ADV"):
            continue
        base, degree = _degree(tok)
        if base not in _EVALUATIVE:
            continue
        comparative, superlative = degree == "comparative", degree == "superlative"
        if not (comparative or superlative):
            continue
        # Who the comparison is about: the noun it modifies, or the subject of "be".
        noun = tok.head if tok.dep_ == "amod" else None
        target = noun
        if noun is not None and noun.dep_ == "attr":
            target = next((c for c in noun.head.children if c.dep_ == "nsubj"), noun)
        if tok.dep_ in ("acomp", "attr"):
            target = next((c for c in tok.head.children if c.dep_ == "nsubj"), None)
        if re.search(r"\bthan (?:ours|us|our)\b", low):
            add("superiority", f'"{tok.text} than ours"', tok, check_neg=False)
        elif comparative and about_group(target) and _THAN_OTHERS.search(sent_text):
            # "Our people are braver than any other": a comparison with other groups.
            add("superiority", f'"{tok.text}" than others, said of the group', tok)
        elif superlative and about_group(target) and (
                (noun is not None and noun.lemma_.lower() in _GROUP_NOUNS) or _WORLD_FRAME.search(sent_text)):
            # "We are the greatest nation", "the best in the world" (not "our greatest strength").
            add("superiority", f'"{tok.text}" said of the group', tok)
    for rx in _SUPERIOR_RES:
        if (m := rx.search(sent_text)):
            add("superiority", f'"{m.group(0)}"', tok_near(sent_start + m.start()),
                check_neg=not m.group(0).lower().startswith("no "))
    # Differentiation: our side and theirs set against each other.
    if out_present and self_toks:
        marks = [t for t in toks if t.lower_ in _CONTRAST and t.dep_ in ("mark", "cc", "advmod", "prep")]
        if marks:
            add("differentiation", f'contrast "{marks[0].text}" between the group and others', check_neg=False)
    for rx in _CONTRAST_RES:
        if (m := rx.search(sent_text)):
            add("differentiation", f'"{m.group(0)}"', check_neg=False)
    # Hostility / exclusion aimed at another group.
    for tok in toks:
        lem = tok.lemma_.lower()
        if tok.pos_ in ("NOUN", "PROPN") and lem in _HOSTILE_NOUNS:
            # "our enemies", "they are traitors", "the invaders": the noun names an out-group.
            # "We are not terrorists" describes the speaker's side: not hostility.
            if tok.dep_ == "attr" and any(c.dep_ == "nsubj" and (_is_self_plural(c) or c.lower_ in _SELF_SING)
                                          for c in tok.head.children):
                continue
            add("hostility", f'"{tok.text}"', tok, check_neg=tok.dep_ in ("attr", "acomp"))
        elif tok.pos_ == "ADJ" and lem in _HOSTILE_ADJ:
            target = tok.head if tok.dep_ == "amod" else next((c for c in tok.head.children if c.dep_ == "nsubj"), None)
            if target is not None and not _is_self_plural(target) and target.lower_ not in _SELF_SING \
                    and target.i not in in_group_heads:
                add("hostility", f'"{tok.text}" said of others', tok, check_neg=tok.dep_ in ("acomp", "attr"))
        elif tok.pos_ == "VERB" and lem in _HOSTILE_VERBS:
            subj = next((c for c in tok.children if c.dep_ == "nsubj"), None)
            if subj is None and tok.dep_ == "xcomp":   # "they want to destroy us"
                subj = next((c for c in tok.head.children if c.dep_ == "nsubj"), None)
            obj = next((c for c in tok.children if c.dep_ == "dobj"), None)
            if subj is not None and not _is_self_plural(subj) and subj.lower_ not in _SELF_SING and (
                    obj is not None and (_is_self_plural(obj) or obj.i in in_group_heads
                                         or any(_is_self_plural(c) for c in obj.children))):
                add("hostility", f'others "{tok.text}" the group', tok)
    for rx in _EXCLUDE_RES:
        if (m := rx.search(sent_text)):
            add("hostility", f'exclusion: "{m.group(0)}"', tok_near(sent_start + m.start()))
    return cats, negated


# --------------------------------------------------------------------------- #
# Arabic: word cues (no parser)
# --------------------------------------------------------------------------- #
_AR_PRON = {"نحن", "اننا", "لنا", "علينا", "منا", "بنا", "عندنا", "معنا", "لدينا", "انا"}
_AR_NOUN_TARGET = {
    "nation": ("بلاد", "بلد", "وطن", "دوله", "شعب", "امه", "ارض", "حدود", "سياده", "مواطن", "مواطني", "تراب",
               "استقلال", "دستور", "علم", "اقتصاد", "تاريخ", "هويه"),
    "government": ("حكومه", "اداره", "وزاره"),
    "party": ("حزب", "حركه"),
    "military": ("جيش", "قوات", "جنود", "مقاتلي", "مجاهدي"),
    "org": ("منظمه", "اتحاد", "تحالف", "تكتل", "مجموعه", "مجلس", "منتدي", "جامعه", "قمه"),
    "multi": ("تعاون", "شراكه", "شركاء", "تضامن", "وحده", "تكامل", "مصالح المشتركه"),
    "continent": ("قاره",),
    "region": ("منطقه", "اقليم"),
    "world": ("عالم", "انسانيه", "كوكب"),
    "faith": ("دين", "عقيده", "ايمان", "امه الاسلاميه", "رسول", "نبي"),
}
_AR_PREFIXES = ("وبال", "فبال", "وال", "فال", "بال", "كال", "لل", "ال", "و", "ف", "ب", "ل", "ك")
_AR_PREF = re.compile(r"(?:\S+ اولا|الاولويه|على حساب|قبل مصالح|فوق مصالح|فوق كل اعتبار)")
_AR_SUP = re.compile(r"(?:اعظم|افضل من|خير امه|لا مثيل|الاقوي|اقوي من|ارقي|اعرق|الاعظم)")
_AR_DIFF = re.compile(r"(?:بينما هم|اما هم|على عكسهم|على عكس|في حين ان|بخلاف)")
_AR_HOST = re.compile(r"(?:عدو|اعداء|خونه|خائن|غزاه|الغزاه|محتل|الاحتلال|ارهابي|متامر|مؤامره|المتامرين|تهديد)")
_AR_OUT = re.compile(r"(?:^|\s)(?:هم|لهم|عليهم|منهم|بهم|عندهم|الاجانب|الغرب|الاخرين)(?:\s|$)")
_AR_REPORT = re.compile(r"(?:^|\s)(?:قال|يقول|قالوا|يقولون|زعم|يزعم|يزعمون|ادعي|يدعي|يدعون|صرح|وفقا ل)")
_AR_SELF_REPORT = re.compile(r"(?:^|\s)(?:قلت|اقول|نقول|قلنا)")
_AR_NEG = re.compile(r"(?:^|\s)(?:لا|لن|لم|ليس|ليست|لسنا|ما)(?:\s|$)")
_AR_COND = re.compile(r"(?:^|\s)(?:اذا|لو|ان|لولا)(?:\s)")


def _ar_stem_target(tok: str) -> tuple[str, str] | None:
    """For a word ending in -نا ("our"): (target, stem) when the stem is a group noun."""
    if not tok.endswith("نا") or len(tok) < 4:
        return None
    word = tok[:-2]
    # A first و or ب may be a prefix ("وبلادنا") or part of the word ("وطننا", "بلادنا"): try both.
    stems = {word} | {word[len(p):] for p in _AR_PREFIXES if word.startswith(p) and len(word) - len(p) >= 2}
    cands = stems | {s[:-1] + "ه" for s in stems if s.endswith("ت")}   # دولتنا -> دوله
    for target, words in _AR_NOUN_TARGET.items():
        hit = cands & set(words)
        if hit:
            return target, sorted(hit, key=len)[-1]
    return None


# --------------------------------------------------------------------------- #
# The analysis
# --------------------------------------------------------------------------- #
def _resolve_target(target: str, sent_named: dict, recent_orgs: list[str], recent_named: set[str],
                    setting: dict, groups_by: dict, own_orgs: list[str]) -> tuple[str | None, str]:
    """Group key for a cue target, and how it was found."""
    if target in ("nation", "government", "party"):
        return target, ""
    if target == "military":
        if groups_by["military"]["recorded"]:
            return "military", ""
        if own_orgs and not groups_by["government"]["recorded"]:
            return own_orgs[0], "the speaker's own organisation (role)"
        return "nation", "national armed forces"
    if target in ("org", "multi"):
        named_orgs = [k for k in sent_named if groups_by[k]["kind"] == "organization"]
        if named_orgs:
            return named_orgs[0], "organisation named in the sentence"
        if recent_orgs:
            return recent_orgs[-1], "organisation named just before"
        host = setting.get("host_entity")
        if host and f"org:{host}" in groups_by:
            return f"org:{host}", f"speech setting ({setting['host']['name']}, {setting.get('source')})"
        if target == "org" and own_orgs:
            return own_orgs[0], "the speaker's own organisation (role)"
        if target == "multi" and setting.get("type") == "national":
            # "our collective resolve", "together" to a national audience: the nation.
            return "nation", "shared wording, national setting"
        return "partnership", "no organisation named nearby"
    if target == "continent":
        named = [k for k in list(sent_named) + sorted(recent_named) if k.startswith("col:C-")]
        if named:
            return named[0], "continent named nearby"
        rec = [f"col:{c}" for o, c in _CONTINENT_OF_ORG.items() if f"org:{o}" in groups_by and groups_by[f"org:{o}"]["recorded"]]
        if rec:
            return rec[0], "recorded continental membership"
        return None, "continent not named"
    if target == "region":
        named = [k for k in sent_named if groups_by[k]["kind"] == "organization"] or recent_orgs
        if named:
            return named[-1], "regional organisation named nearby"
        return None, "region not named"
    if target == "world":
        return "col:INTL", ""
    if target == "faith":
        return ("col:ISLAM" if "col:ISLAM" in sent_named or "col:ISLAM" in recent_named else "religious"), ""
    return None, ""


def _confidence(best: float, second: float, inherited: bool) -> str | None:
    if inherited:
        return "low"
    if best < 2 or (second and second >= best * 0.75):
        return None
    if best >= 4 and second < best * 0.5:
        return "high"
    return "medium" if best >= 3 or not second else "low"


def analyze(text: str, speaker: str | None = None, setting: dict | None = None,
            decisions: list[dict] | None = None, affiliations: list[str] | None = None,
            home: str | None = None, role: str | None = None) -> dict:
    """Contextual in-group analysis of one speech (see the module docstring).

    `speaker` is a stakeholder id: their role, home country and recorded memberships
    supply the candidate groups. `affiliations`, `home` and `role` override them
    (tests, or a speaker who isn't on file). `setting` is the speech's metadata
    (event, host, audience, location, date). `decisions` are reviewed sentences:
    [{"sentence": i, "group": key | "ambiguous", "voice": ..., "cats": [...], "source": "ai" | "person"}].
    """
    if speaker and (home is None or role is None or affiliations is None):
        sp_home, sp_role, sp_aff = speaker_records(speaker)
        home = sp_home if home is None else home
        role = sp_role if role is None else role
        affiliations = sp_aff if affiliations is None else affiliations
    role, affiliations = role or "", affiliations or []
    is_ar = arabic.is_arabic(text)
    sents = _sentences(text)
    ctx = detect_setting(text, sents, setting)
    groups = candidate_groups(text, home, role, affiliations, ctx)
    by = {g["key"]: g for g in groups}
    own_orgs = [g["key"] for g in groups if g["relation_source"] == "stakeholder role" and g["kind"] == "organization"]
    quotes = _quote_spans(text)
    paras = _paragraph_breaks(text, sents)
    doc = None if is_ar else _parsed(text)
    overrides = {}
    for d in decisions or []:
        try:
            overrides[int(d["sentence"])] = d
        except (KeyError, TypeError, ValueError):
            continue

    passages: list[dict] = []
    recent_orgs: list[str] = []
    recent_named: set[str] = set()
    prev_resolved: str | None = None
    for i, (s, e) in enumerate(sents):
        if paras[i]:
            recent_orgs, recent_named = [], set()
        carried, prev_resolved = (None if paras[i] else prev_resolved), None
        sent_text = text[s:e]
        named = _mentions(groups, text, s, e, is_ar)
        if is_ar:
            refs, cats, negated, modality = _arabic_sentence(sent_text, s, named, recent_orgs, recent_named,
                                                             ctx, by, own_orgs, home, quotes)
        else:
            refs, cats, negated, modality = _english_sentence(doc, text, s, e, named, recent_orgs, recent_named,
                                                              ctx, by, own_orgs, home, quotes, groups, carried)
        if refs:
            res = [r for r in refs if r["group"]]
            primary = None
            if res:
                tally: dict[str, float] = {}
                for r in res:
                    tally[r["group"]] = tally.get(r["group"], 0) + 1
                order = [r["group"] for r in res]
                primary = max(tally, key=lambda k: (tally[k], -order.index(k)))
            voice = "own" if any(r["voice"] == "own" for r in refs) else refs[0]["voice"]
            conf = next((r["confidence"] for r in res if r["group"] == primary), None) if primary else None
            passages.append(_passage(i, s, e, sent_text, refs, cats, negated, modality, voice, primary,
                                     conf or "none", sorted({r["group"] for r in res}), ""))
            if primary and conf in ("high", "medium") and voice == "own":
                prev_resolved = primary
        elif cats.get("hostility"):
            # Hostility toward others with no collective pronoun: listed, attributed to no group.
            voice = "own"
            if any(a < s + 1 < b for a, b in quotes) or _OTHERS_VIEW.search(sent_text):
                voice = "quoted"
            passages.append(_passage(i, s, e, sent_text, [], {"hostility": cats["hostility"]}, negated, modality,
                                     voice, None, "none", [], "Hostility toward another group; no in-group named"))
        # What this sentence names, for the next ones.
        for k in named:
            if by[k]["kind"] == "organization" and k not in recent_orgs:
                recent_orgs = (recent_orgs + [k])[-2:]
            if k.startswith("col:"):
                recent_named.add(k)

    for p in passages:
        d = overrides.get(p["i"])
        if d:
            _apply_decision(p, d, by)
    return _summarize(passages, groups, ctx, text)


def _english_sentence(doc, text, s, e, named, recent_orgs, recent_named, ctx, by, own_orgs, home, quotes,
                      groups, prev_resolved):
    """(references, categories, negated cues, modality) for one English sentence."""
    sent_text = text[s:e]
    toks = _tokens_in(doc, s, e)
    selfs = [t for t in toks if _is_self_plural(t)]
    out_present = any(t.lower_ in _OUT_PRON for t in toks) or any(
        t.lemma_.lower() in _OUT_NOUNS and t.pos_ in ("NOUN", "PROPN") for t in toks) or any(
        m["key"] != home and entities.ENTITIES[m["key"]]["kind"] == "country" for m in _found_in(text, s, e))
    cats, negated = _category_cues(toks, sent_text, selfs, out_present, s)
    modality = _modality(selfs[0] if selfs else (toks[0] if toks else None), sent_text)
    if not selfs:
        return [], cats, negated, modality
    low = sent_text.lower()
    sent_cues = [(target, w, f'"{phrase}"') for phrase, (target, w) in _SENT_CUES.items() if phrase in low]
    raw = []
    for t in selfs:
        noun = _possessed(t)
        owner = "our" if t.dep_ == "poss" else f"{t.text} {t.head.text} ..."
        raw.append({"t": t, "cues": _noun_cues(noun, owner) if noun is not None else [],
                    "direct": _appositive_cues(t, text, s, groups)})
    # Possessives in a sentence usually share the pronoun's group: "We must protect our
    # sovereignty" -> "we" takes the cues of "our sovereignty".
    pooled = [c for r in raw for c in r["cues"]]
    pooled_direct = [c for r in raw for c in r["direct"]]
    refs = []
    for r in raw:
        cues = (r["cues"] or pooled) + sent_cues
        direct = r["direct"] or ([] if r["cues"] else pooled_direct)
        score: dict[str, float] = {}
        why: dict[str, list[str]] = {}
        unresolved: list[str] = []
        for k, w, reason in direct:
            score[k] = score.get(k, 0) + w
            why.setdefault(k, []).append(f"{reason} names the group")
        for target, w, reason in cues:
            k, how = _resolve_target(target, named, recent_orgs, recent_named, ctx, by, own_orgs)
            if k is None:
                unresolved.append(f"{reason}: {how}")
                continue
            score[k] = score.get(k, 0) + w
            why.setdefault(k, []).append(reason + (f" ({how})" if how else ""))
        for k in named:
            if by[k]["kind"] in ("organization", "collective", "religious", "nation"):
                score[k] = score.get(k, 0) + 1
                why.setdefault(k, []).append(f"{by[k]['name']} named in the sentence")
        ranked = sorted(score.items(), key=lambda x: -x[1])
        inherited = False
        if not ranked and prev_resolved and r["t"].lower_ in ("we", "us"):
            ranked, inherited = [(prev_resolved, 1.0)], True
            why.setdefault(prev_resolved, []).append("carried from the previous sentence")
        best_k, best = ranked[0] if ranked else (None, 0.0)
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        conf = _confidence(best, second, inherited) if best_k else None
        if conf:
            reasons = why.get(best_k, [])
        elif ranked:
            reasons = ["Not enough to decide: " + ", ".join(f"{by[k]['name']} ({v:g})" for k, v in ranked[:3])]
        else:
            reasons = ["No cue in or around the sentence says who 'we' are"]
        t = r["t"]
        refs.append({"expr": t.text, "start": t.idx, "end": t.idx + len(t.text),
                     "group": best_k if conf else None, "confidence": conf, "why": reasons + unresolved,
                     "voice": _voice(t.idx, t, text, (s, e), quotes, sent_text),
                     "candidates": [k for k, _ in ranked[:3]]})
    return refs, cats, negated, modality


def _arabic_sentence(sent_text: str, s: int, named: dict, recent_orgs: list, recent_named: set, ctx: dict,
                     by: dict, own_orgs: list, home, quotes):
    """(references, categories, negated cues, modality) for one Arabic sentence (word cues only)."""
    norm = arabic.normalize(sent_text)
    toks = arabic.tokens(sent_text)
    exprs = [t for t in toks if t in _AR_PRON or (t.endswith("نا") and len(t) > 3)]
    out_present = bool(_AR_OUT.search(norm)) or any(
        m["key"] != home and entities.ENTITIES[m["key"]]["kind"] == "country"
        for m in entities.find(sent_text))
    cats: dict[str, list[str]] = {}
    for name, rx in (("preference", _AR_PREF), ("superiority", _AR_SUP)):
        if (m := rx.search(norm)):
            cats[name] = [f'"{m.group(0)}"']
    if (m := _AR_DIFF.search(norm)) and out_present:
        cats["differentiation"] = [f'"{m.group(0)}"']
    if (m := _AR_HOST.search(norm)) and (out_present or exprs):
        cats["hostility"] = [f'"{m.group(0)}"']
    negated = []
    neg = _AR_NEG.search(norm)
    if neg:
        for c in list(cats):
            cue = cats[c][0].strip('"')
            at = norm.find(cue)
            if at >= 0 and 0 <= at - neg.end() <= 20:
                negated.append(f"{c}: {cats.pop(c)[0]} (negated)")
    modality = []
    if _AR_COND.search(" " + norm[:14]):
        modality.append("hypothetical")
    if sent_text.rstrip().endswith(("؟", "?")):
        modality.append("question")
    if "ما يسمي" in norm:
        modality.append("irony")
    if not exprs:
        return [], cats, negated, modality
    score: dict[str, float] = {}
    why: dict[str, list[str]] = {}
    for t in exprs:
        hit = _ar_stem_target(t)
        if not hit:
            continue
        k, how = _resolve_target(hit[0], named, recent_orgs, recent_named, ctx, by, own_orgs)
        if k:
            score[k] = score.get(k, 0) + 3
            why.setdefault(k, []).append(f'"{t}"' + (f" ({how})" if how else ""))
    if "المشتركه" in norm:
        k, how = _resolve_target("multi", named, recent_orgs, recent_named, ctx, by, own_orgs)
        if k:
            score[k] = score.get(k, 0) + 2
            why.setdefault(k, []).append('"المشتركة"' + (f" ({how})" if how else ""))
    for k in named:
        score[k] = score.get(k, 0) + 1
        why.setdefault(k, []).append(f"{by[k]['name']} named in the sentence")
    ranked = sorted(score.items(), key=lambda x: -x[1])
    best_k, best = ranked[0] if ranked else (None, 0)
    second = ranked[1][1] if len(ranked) > 1 else 0
    conf = _confidence(best, second, False) if best_k else None
    voice = "own"
    if any(a <= s < b or s <= a < s + len(sent_text) for a, b in quotes) or re.search(r"«[^»]*»", sent_text):
        voice = "quoted"
    elif _AR_REPORT.search(norm) and not _AR_SELF_REPORT.search(norm):
        voice = "reported"
    if conf:
        reasons = why.get(best_k, [])
    elif ranked:
        reasons = ["Not enough to decide: " + ", ".join(by[k]["name"] for k, _ in ranked[:3])]
    else:
        reasons = ["No cue in or around the sentence says who 'we' are"]
    ref = {"expr": " ".join(dict.fromkeys(exprs))[:60], "start": s, "end": s, "group": best_k if conf else None,
           "confidence": conf, "voice": voice, "candidates": [k for k, _ in ranked[:3]], "why": reasons}
    return [ref], cats, negated, modality


def _passage(i, s, e, sent_text, refs, cats, negated, modality, voice, primary, conf, groups, note) -> dict:
    counted = voice == "own" and primary is not None and primary != "partnership"
    flags = [c for c in BIAS if c in cats]
    p = {"i": i, "start": s, "end": e, "text": " ".join(sent_text.split()), "refs": refs,
         "group": primary, "groups": groups, "confidence": conf, "voice": voice, "modality": modality,
         "negated": negated, "rule_categories": flags, "reasons": dict(cats), "note": note, "source": "rules"}
    _settle(p, counted)
    return p


def _settle(p: dict, counted: bool) -> None:
    """counted / bias / categories from the passage's group, voice, modality and flags."""
    flags = p["rule_categories"]
    p["counted"] = counted
    # A hypothetical, a question or "so-called" is the speaker's sentence about the group
    # (it counts as a reference) but not a claim of bias.
    p["bias"] = counted and bool(flags) and not p["modality"]
    if p["bias"]:
        p["categories"] = list(flags)
    else:
        p["categories"] = ["identification"] if p["group"] else list(flags)


def _apply_decision(p: dict, d: dict, by: dict) -> None:
    """A reviewed sentence (AI or person): referent, voice and categories replaced."""
    g = d.get("group")
    src = d.get("source") if d.get("source") in ("ai", "person") else "person"
    if g == "ambiguous":
        p["group"], p["confidence"] = None, "none"
    elif g in by:
        p["group"], p["confidence"] = g, "reviewed"
        p["groups"] = sorted(set(p["groups"]) | {g})
    v = d.get("voice")
    if v in ("own", "quoted", "reported"):
        p["voice"] = v
        if v == "own":
            p["modality"] = []
    elif v in ("negated", "hypothetical", "question", "irony"):
        p["voice"] = "own"
        p["modality"] = [v]
    if isinstance(d.get("cats"), list):
        flags = [c for c in d["cats"] if c in BIAS]
        p["rule_categories"] = flags
        p["reasons"] = {c: p["reasons"].get(c) or [f"judged by {src}"] for c in flags}
    _settle(p, p["voice"] == "own" and p["group"] is not None and p["group"] != "partnership")
    p["source"] = src
    if d.get("note"):
        p["note"] = str(d["note"])[:300]


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _band(share: float) -> str:
    return "Low" if share < LOW_BELOW else "High" if share >= HIGH_FROM else "Moderate"


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - m) / d), min(1.0, (c + m) / d)


def assess(refs: int, bias: int, low_conf: int = 0) -> dict:
    """Band, share and confidence for one group's counts (the deterministic rule)."""
    if refs < MIN_REFS:
        return {"assessment": "Insufficient evidence", "share": None, "interval": None,
                "confidence": "insufficient", "references": refs, "bias_sentences": bias}
    share = bias / refs
    lo, hi = _wilson(bias, refs)
    conf = "high" if refs >= 25 else "medium" if refs >= 10 else "low"
    if low_conf > refs / 2 and conf != "low":
        conf = "medium" if conf == "high" else "low"
    return {"assessment": _band(share), "share": round(share, 3), "interval": [round(lo, 3), round(hi, 3)],
            "confidence": conf, "references": refs, "bias_sentences": bias}


def _summarize(passages: list[dict], groups: list[dict], setting: dict, text: str) -> dict:
    by = {g["key"]: g for g in groups}
    stats: dict[str, dict] = {}
    for p in passages:
        k = p["group"]
        if not k:
            continue
        st = stats.setdefault(k, {"refs": 0, "bias": 0, "low": 0, "excluded": 0,
                                  **{c: 0 for c in CATEGORIES}})
        if not p["counted"]:
            st["excluded"] += 1
            continue
        st["refs"] += 1
        st["low"] += p["confidence"] == "low"
        st["bias"] += p["bias"]
        for c in p["categories"]:
            st[c] += 1
    out_groups = []
    for k, st in stats.items():
        g = by[k]
        a = assess(st["refs"], st["bias"], st["low"]) if k != "partnership" else \
            {"assessment": "Not assessed (group not named)", "share": None, "interval": None,
             "confidence": "insufficient", "references": st["refs"], "bias_sentences": st["bias"]}
        out_groups.append({**{x: g[x] for x in ("key", "kind", "name", "name_ar", "relation", "relation_source",
                                                "recorded", "entity")},
                           **a, "counts": {c: st[c] for c in CATEGORIES}, "excluded": st["excluded"],
                           "low_confidence_refs": st["low"]})
    out_groups.sort(key=lambda g: (-g["references"], g["name"]))
    pooled = [g for g in out_groups if g["key"] != "partnership"]
    total_refs = sum(g["references"] for g in pooled)
    total_bias = sum(g["bias_sentences"] for g in pooled)
    overall = assess(total_refs, total_bias, sum(g["low_confidence_refs"] for g in pooled))
    overall["groups_pooled"] = [g["key"] for g in pooled if g["references"]]
    ambiguous = [p for p in passages if p["refs"] and not p["group"]]
    hostile_unattributed = [p for p in passages if not p["refs"] and p["categories"] == ["hostility"]]
    return {"method": METHOD, "setting": setting, "overall": overall, "groups": out_groups,
            "candidates": [{x: g[x] for x in ("key", "kind", "name", "name_ar", "relation", "recorded")}
                           for g in groups],
            "passages": passages, "ambiguous": len(ambiguous),
            "hostility_without_ingroup": len(hostile_unattributed),
            "collective_sentences": sum(1 for p in passages if p["refs"]),
            "language": "ar" if arabic.is_arabic(text) else "en"}


# --------------------------------------------------------------------------- #
# Speakers on file
# --------------------------------------------------------------------------- #
def speaker_records(sid: str) -> tuple[str | None, str, list[str]]:
    """(home country, role, memberships) as recorded for a stakeholder (edits included)."""
    from . import dossier
    from . import stakeholders as stk
    person = next((s for s in stk.STAKEHOLDERS if s["id"] == sid), None)
    if person is None:
        return None, "", []
    prof = {**(dossier.PROFILES.get(sid) or {}), **stk.profile_edit(sid)}
    return stk.home_country(sid), person.get("role") or "", list(prof.get("memberships") or [])


@lru_cache(maxsize=8)
def _parsed(text: str):
    from .nlp import parsed
    return parsed(text)


def merge(results: list[tuple[dict, dict]]) -> dict:
    """Several speeches of one speaker: per-group counts added up, with each speech
    kept separate (title, setting, how many sentences) so the contexts stay visible.
    `results` is [(speech info, analyze() result)]."""
    groups: dict[str, dict] = {}
    for sp, r in results:
        for g in r["groups"]:
            m = groups.setdefault(g["key"], {**{k: g[k] for k in ("key", "kind", "name", "name_ar", "relation",
                                                                    "relation_source", "recorded", "entity")},
                                             "refs": 0, "bias": 0, "low": 0, "excluded": 0,
                                             "counts": {c: 0 for c in CATEGORIES}, "speeches": []})
            m["refs"] += g["references"]
            m["bias"] += g["bias_sentences"]
            m["low"] += g["low_confidence_refs"]
            m["excluded"] += g["excluded"]
            for c in CATEGORIES:
                m["counts"][c] += g["counts"][c]
            m["speeches"].append({"id": sp.get("id"), "title": sp.get("title") or "", "added": sp.get("added"),
                                  "setting": _setting_line(r["setting"]), "references": g["references"],
                                  "bias_sentences": g["bias_sentences"]})
    out = []
    for m in groups.values():
        a = assess(m["refs"], m["bias"], m["low"]) if m["key"] != "partnership" else \
            {"assessment": "Not assessed (group not named)", "share": None, "interval": None,
             "confidence": "insufficient", "references": m["refs"], "bias_sentences": m["bias"]}
        out.append({**{k: v for k, v in m.items() if k not in ("refs", "bias", "low")}, **a,
                    "low_confidence_refs": m["low"]})
    out.sort(key=lambda g: (-g["references"], g["name"]))
    pooled = [g for g in out if g["key"] != "partnership"]
    overall = assess(sum(g["references"] for g in pooled), sum(g["bias_sentences"] for g in pooled),
                     sum(g["low_confidence_refs"] for g in pooled))
    return {"method": METHOD, "overall": overall, "groups": out, "speeches": len(results)}


def _setting_line(st: dict) -> str:
    bits = []
    md = st.get("metadata") or {}
    for k in ("event", "host", "location", "date", "audience"):
        if md.get(k):
            bits.append(md[k])
    if not bits:
        if st.get("host"):
            bits.append(f"{st['host']['name']} (from the text)")
        if st.get("type") != "unclear":
            bits.append(f"{st['type']} audience (from the text)")
    return " · ".join(bits) or "Setting not recorded"


def organisation_view(sid: str, key: str, results: list[tuple[dict, dict]], records: tuple) -> dict:
    """One group's assessment for one speaker, with the passages that support it."""
    merged = merge(results)
    g = next((x for x in merged["groups"] if x["key"] == key), None)
    home, role, aff = records
    if g is None:
        cand = next((c for _sp, r in results for c in r["candidates"] if c["key"] == key), None)
        if cand is None:
            cands = candidate_groups("", home, role, aff, {"host_entity": None})
            cand = next((c for c in cands if c["key"] == key), None)
        if cand is None:
            return {}
        g = {**{k: cand.get(k) for k in ("key", "kind", "name", "name_ar", "relation", "recorded")},
             **assess(0, 0), "counts": {c: 0 for c in CATEGORIES}, "speeches": [], "excluded": 0}
    quotes = {"identification": [], "preference": [], "superiority": [], "differentiation": [], "hostility": [],
              "excluded": [], "ambiguous": []}
    for sp, r in results:
        for p in r["passages"]:
            item = {"text": p["text"], "speech": sp.get("title") or "", "setting": _setting_line(r["setting"]),
                    "confidence": p["confidence"], "voice": p["voice"], "reasons": p["reasons"],
                    "why": [w for ref in p["refs"] if ref.get("group") == key for w in ref.get("why", [])][:3],
                    "source": p["source"]}
            if p["group"] == key:
                if not p["counted"]:
                    quotes["excluded"].append(item)
                else:
                    for c in p["categories"]:
                        quotes[c].append(item)
            elif not p["group"] and key in (ref for x in p["refs"] for ref in x.get("candidates", [])):
                quotes["ambiguous"].append(item)
    return {**g, "quotes": {k: v[:40] for k, v in quotes.items()}, "method": METHOD}


# --------------------------------------------------------------------------- #
# Karnak's check of the doubtful sentences
# --------------------------------------------------------------------------- #
_AI_PROMPT = """You check how a political speech uses collective language (we, us, our). \
For each numbered sentence decide, using the sentence, the sentences around it and the speech setting:

"ref": which group the speaker's "we/us/our" means. Use ONLY a key from GROUPS, or "AMBIG" \
when the text does not show it. Do not assume the host organisation; use the words.
"voice": "own" (the speaker's own view), "quoted" (words of someone else in quotation marks), \
"reported" (someone else's view described), "negated", "hypothetical" (if/would/imagine), \
"question", "irony".
"cats": the bias indicators the sentence shows about that group, from: \
PREF = puts the group's interests before others'; SUP = group better, more legitimate or more \
deserving; DIFF = draws a line between the group and another group; HOST = another group shown \
as a threat, enemy, inferior or excluded. Belonging, solidarity or common purpose alone is NOT a \
bias indicator: give [] for it.

Respond ONLY with JSON: {"s": [{"i": 3, "ref": "nation", "voice": "own", "cats": []}]}"""
_AI_CATS = {"PREF": "preference", "SUP": "superiority", "DIFF": "differentiation", "HOST": "hostility"}
AI_GROUP = 8
AI_MAX = 64


def ai_targets(result: dict) -> list[dict]:
    """The sentences worth a second look: ambiguous or low-confidence referents, and
    every sentence the rules marked as bias or set aside."""
    out = []
    for p in result["passages"]:
        if not p["refs"]:
            continue
        if (not p["group"] or p["confidence"] == "low" or p["bias"] or p["voice"] != "own") and p["source"] == "rules":
            out.append(p)
    return out[:AI_MAX]


def ai_check(text: str, speaker: str | None = None, setting: dict | None = None,
             decisions: list[dict] | None = None, **records) -> dict:
    """Ask Karnak about the doubtful sentences; returns {"decisions": [...], "result": ...}.
    `records` (home, role, affiliations) override the speaker's records, as in analyze()."""
    from . import llm
    chat_json = llm.chat_json
    base = analyze(text, speaker, setting, decisions, **records)
    targets = ai_targets(base)
    keys = {c["key"] for c in base["candidates"]}
    group_lines = "\n".join(f"{c['key']}: {c['name']} (speaker's relation: {c['relation']})" for c in base["candidates"])
    st = base["setting"]
    setting_line = _setting_line(st)
    sents = _sentences(text)
    made: list[dict] = []
    for n in range(0, len(targets), AI_GROUP):
        chunk = targets[n:n + AI_GROUP]
        lines = []
        for p in chunk:
            before = " ".join(text[sents[p["i"] - 1][0]:sents[p["i"] - 1][1]].split())[-240:] if p["i"] else ""
            lines.append(f"{p['i']}: {p['text'][:600]}\n   before: {before}\n   rules said: "
                         f"ref={p['group'] or 'AMBIG'}, voice={p['voice']}, cats={[c for c in p['categories'] if c in BIAS]}")
        answer, _ = chat_json([{"role": "system", "content": _AI_PROMPT},
                               {"role": "user", "content": f"SETTING: {setting_line}\n\nGROUPS:\n{group_lines}\n\n"
                                                           "SENTENCES:\n" + "\n".join(lines)}], temperature=0.1)
        rows = answer.get("s") if isinstance(answer, dict) else None
        wanted = {p["i"]: p for p in chunk}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                i = int(row.get("i"))
            except (TypeError, ValueError):
                continue
            if i not in wanted:
                continue
            p = wanted[i]
            ref = str(row.get("ref") or "").strip()
            d: dict = {"sentence": i, "source": "ai"}
            notes = []
            # Safeguards: the AI may resolve what the rules left open, or make them more
            # cautious; it does not overturn structural evidence the rules found.
            ai_group = "ambiguous" if ref.upper() == "AMBIG" else ref if ref in keys else None
            if ai_group:
                if p["group"] and p["confidence"] in ("high", "medium") and ai_group != p["group"]:
                    notes.append(f"Karnak suggested: {ai_group}")
                else:
                    d["group"] = ai_group
            voice = str(row.get("voice") or "").strip().lower()
            if voice in VOICES:
                if p["voice"] in ("quoted", "reported") and voice == "own":
                    notes.append("Karnak read it as the speaker's own words; quotation/reporting kept")
                else:
                    d["voice"] = voice
            cats = row.get("cats")
            if isinstance(cats, list):
                d["cats"] = [_AI_CATS[c] for c in (str(x).strip().upper() for x in cats) if c in _AI_CATS]
                if sorted(d["cats"]) != sorted(p["rule_categories"]):
                    notes.append(f"rules found: {', '.join(p['rule_categories']) or 'no bias cue'}")
            if notes:
                d["note"] = "; ".join(notes)
            if len(d) > 2:
                made.append(d)
    # A person's decision always wins over Karnak's.
    keep = [d for d in (decisions or []) if d.get("source") == "person"]
    person_at = {d["sentence"] for d in keep}
    merged = keep + [d for d in made if d["sentence"] not in person_at]
    return {"decisions": merged, "checked": len(targets),
            "result": analyze(text, speaker, setting, merged, **records)}


# --------------------------------------------------------------------------- #
# Change over time, for the profile's "See data"
# --------------------------------------------------------------------------- #
FLASH_SHIFT = 0.25      # bias share moving this much from the speeches before = a flash point
FLASH_MIN_REFS = 3      # sentences about the group needed in the speech, and before it
FLASH_RULE = (f"A speech is flagged when its bias share for a group differs by at least {int(FLASH_SHIFT * 100)} "
              f"percentage points from all the earlier speeches pooled, with at least {FLASH_MIN_REFS} sentences "
              "about the group in that speech and before it. Speeches are in date order: the date in the "
              "speech setting, else the date it was saved.")


def timeline(results: list[tuple[dict, dict]]) -> dict:
    """Per group, the speeches in date order: sentences examined, bias sentences, share,
    and flash points."""
    rows = sorted(results, key=lambda x: x[0].get("date") or "")
    groups: dict[str, dict] = {}
    for sp, r in rows:
        for g in r["groups"]:
            if g["key"] == "partnership":
                continue
            m = groups.setdefault(g["key"], {"key": g["key"], "name": g["name"], "name_ar": g["name_ar"],
                                              "examined": 0, "points": []})
            m["examined"] += g["references"]
            m["points"].append({"id": sp.get("id"), "title": sp.get("title") or "", "date": sp.get("date"),
                                "references": g["references"], "bias_sentences": g["bias_sentences"],
                                "share": round(g["bias_sentences"] / g["references"], 3) if g["references"] else None,
                                "flash": False})
    flash = []
    for m in groups.values():
        prior_refs = prior_bias = 0
        for pt in m["points"]:
            if pt["references"] >= FLASH_MIN_REFS and prior_refs >= FLASH_MIN_REFS:
                before = prior_bias / prior_refs
                if abs(pt["share"] - before) >= FLASH_SHIFT:
                    pt["flash"] = True
                    flash.append({"group": m["key"], "name": m["name"], "name_ar": m["name_ar"], "title": pt["title"],
                                  "date": pt["date"], "before": round(before, 3), "after": pt["share"]})
            prior_refs += pt["references"]
            prior_bias += pt["bias_sentences"]
    return {"groups": sorted(groups.values(), key=lambda g: -g["examined"]), "flash_points": flash,
            "rule": FLASH_RULE}
