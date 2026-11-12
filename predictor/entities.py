"""Countries and organizations named in a speech, and how the speaker talks about them.

`find(text)` gives every mention with its character span (for highlighting);
`summarize(text, tones)` groups them per country/organization with the sentences
that name them and a tone per sentence. Without the AI the tone comes from fixed
cue words (predictor.dossier.tone_of); the context check (predictor.context) lets
Karnak or a person set it instead.

English forms are matched case-sensitively as written ("Turkey", not "turkey";
"US", not "us"). Arabic forms are matched on normalized tokens and may carry the
usual one-letter prefixes (و، ف، ب، ل) and "لل" for "ال".
"""
from __future__ import annotations

import re
from functools import lru_cache

from . import arabic
from .dossier import COUNTRIES, tone_of

# key: (English name, Arabic name, kind, English forms, Arabic forms)
_EXTRA_COUNTRIES = {
    "UA": ("Ukraine", "أوكرانيا", ["Ukraine", "Ukrainian", "Kyiv", "Kiev"], ["أوكرانيا", "الأوكراني", "الأوكرانية", "كييف"]),
    "LB": ("Lebanon", "لبنان", ["Lebanon", "Lebanese", "Beirut"], ["لبنان", "اللبناني", "اللبنانية", "بيروت"]),
    "JP": ("Japan", "اليابان", ["Japan", "Japanese", "Tokyo"], ["اليابان", "الياباني", "اليابانية"]),
    "KP": ("North Korea", "كوريا الشمالية", ["North Korea", "North Korean", "Pyongyang", "DPRK"], ["كوريا الشمالية", "بيونغ يانغ"]),
    "KR": ("South Korea", "كوريا الجنوبية", ["South Korea", "South Korean", "Seoul"], ["كوريا الجنوبية", "سيول"]),
    "CA": ("Canada", "كندا", ["Canada", "Canadian", "Ottawa"], ["كندا", "الكندي", "الكندية"]),
    "MX": ("Mexico", "المكسيك", ["Mexico", "Mexican"], ["المكسيك", "المكسيكي", "المكسيكية"]),
    "BR": ("Brazil", "البرازيل", ["Brazil", "Brazilian"], ["البرازيل", "البرازيلي"]),
    "VE": ("Venezuela", "فنزويلا", ["Venezuela", "Venezuelan"], ["فنزويلا", "الفنزويلي"]),
    "IT": ("Italy", "إيطاليا", ["Italy", "Italian", "Rome"], ["إيطاليا", "الإيطالي", "الإيطالية"]),
    "ES": ("Spain", "إسبانيا", ["Spain", "Spanish", "Madrid"], ["إسبانيا", "الإسباني"]),
    "AF": ("Afghanistan", "أفغانستان", ["Afghanistan", "Afghan", "Kabul", "Taliban"], ["أفغانستان", "الأفغاني", "طالبان"]),
    "DZ": ("Algeria", "الجزائر", ["Algeria", "Algerian"], ["الجزائر", "الجزائري", "الجزائرية"]),
    "TN": ("Tunisia", "تونس", ["Tunisia", "Tunisian"], ["تونس", "التونسي", "التونسية"]),
    "SO": ("Somalia", "الصومال", ["Somalia", "Somali", "Mogadishu"], ["الصومال", "الصومالي"]),
    "ER": ("Eritrea", "إريتريا", ["Eritrea", "Eritrean"], ["إريتريا", "الإريتري"]),
    "SS": ("South Sudan", "جنوب السودان", ["South Sudan"], ["جنوب السودان"]),
    "ZA": ("South Africa", "جنوب أفريقيا", ["South Africa", "South African"], ["جنوب أفريقيا", "جنوب إفريقيا"]),
    "NG": ("Nigeria", "نيجيريا", ["Nigeria", "Nigerian"], ["نيجيريا"]),
    "MR": ("Mauritania", "موريتانيا", ["Mauritania", "Mauritanian"], ["موريتانيا"]),
}

_ORGS = {
    "UN": ("United Nations", "الأمم المتحدة",
           ["United Nations", "UN", "U.N.", "Security Council", "General Assembly", "Secretary-General"],
           ["الأمم المتحدة", "مجلس الأمن", "الجمعية العامة", "الأمين العام للأمم المتحدة"]),
    "NATO": ("NATO", "حلف الناتو", ["NATO", "North Atlantic Treaty Organization"],
             ["الناتو", "حلف شمال الأطلسي", "حلف الأطلسي"]),
    "AL": ("Arab League", "جامعة الدول العربية", ["Arab League", "League of Arab States"],
           ["جامعة الدول العربية", "الجامعة العربية"]),
    "AU": ("African Union", "الاتحاد الأفريقي", ["African Union"], ["الاتحاد الأفريقي", "الاتحاد الإفريقي"]),
    "GCC": ("Gulf Cooperation Council", "مجلس التعاون الخليجي", ["Gulf Cooperation Council", "GCC"],
            ["مجلس التعاون الخليجي", "مجلس التعاون لدول الخليج"]),
    "OIC": ("Organisation of Islamic Cooperation", "منظمة التعاون الإسلامي",
            ["Organisation of Islamic Cooperation", "Organization of Islamic Cooperation", "OIC"],
            ["منظمة التعاون الإسلامي"]),
    "IMF": ("IMF", "صندوق النقد الدولي", ["IMF", "International Monetary Fund"], ["صندوق النقد الدولي", "صندوق النقد"]),
    "WB": ("World Bank", "البنك الدولي", ["World Bank"], ["البنك الدولي"]),
    "WHO": ("World Health Organization", "منظمة الصحة العالمية", ["World Health Organization", "WHO"],
            ["منظمة الصحة العالمية"]),
    "WTO": ("World Trade Organization", "منظمة التجارة العالمية", ["World Trade Organization", "WTO"],
            ["منظمة التجارة العالمية"]),
    "OPEC": ("OPEC", "أوبك", ["OPEC", "OPEC+"], ["أوبك", "أوبك بلس"]),
    "BRICS": ("BRICS", "بريكس", ["BRICS"], ["بريكس", "البريكس"]),
    "G7": ("G7", "مجموعة السبع", ["G7", "G-7"], ["مجموعة السبع"]),
    "G20": ("G20", "مجموعة العشرين", ["G20", "G-20"], ["مجموعة العشرين"]),
    "ICC": ("International Criminal Court", "المحكمة الجنائية الدولية", ["International Criminal Court", "ICC"],
            ["المحكمة الجنائية الدولية"]),
    "ICJ": ("International Court of Justice", "محكمة العدل الدولية", ["International Court of Justice", "ICJ", "World Court"],
            ["محكمة العدل الدولية"]),
    "UNRWA": ("UNRWA", "الأونروا", ["UNRWA"], ["الأونروا", "وكالة الأونروا"]),
    "HAMAS": ("Hamas", "حماس", ["Hamas"], ["حماس", "حركة حماس"]),
    "HEZ": ("Hezbollah", "حزب الله", ["Hezbollah", "Hizbollah"], ["حزب الله"]),
    "ISIS": ("ISIS", "داعش", ["ISIS", "ISIL", "Islamic State", "Daesh"], ["داعش", "تنظيم الدولة"]),
    "MB": ("Muslim Brotherhood", "الإخوان المسلمون", ["Muslim Brotherhood"], ["الإخوان المسلمين", "الإخوان المسلمون", "الإخوان", "جماعة الإخوان"]),
}

ENTITIES: dict[str, dict] = {}
for _k, (_en, _ar, _ef, _af) in {**COUNTRIES, **_EXTRA_COUNTRIES}.items():
    ENTITIES[_k] = {"name": _en, "name_ar": _ar, "kind": "organization" if _k == "EU" else "country",
                    "en": _ef, "ar": _af}
for _k, (_en, _ar, _ef, _af) in _ORGS.items():
    ENTITIES[_k] = {"name": _en, "name_ar": _ar, "kind": "organization", "en": _ef, "ar": _af}
# "Palestine" lists "the occupation" for headlines; in a speech that names Israel.
ENTITIES["IL"]["ar"] = [f for f in ENTITIES["IL"]["ar"] if f != "الاحتلال"]


def _en_regex() -> list[tuple[re.Pattern, str]]:
    out = []
    for key, e in ENTITIES.items():
        for form in e["en"]:
            out.append((re.compile(rf"(?<![\w.]){re.escape(form)}(?![\w])"), key))
    return out


_EN = _en_regex()
_AR = sorted(((tuple(arabic.tokens(f)), k) for k, e in ENTITIES.items() for f in e["ar"]),
             key=lambda x: -len(x[0]))
_AR_PREFIX = ("", "و", "ف", "ب", "ل", "ك", "وب", "ول", "فب", "فل", "وك")


def _ar_token_is(tok: str, form: str, first: bool) -> bool:
    if tok == form:
        return True
    if not first:
        return False
    if form.startswith("ال") and tok in ("لل" + form[2:], "ولل" + form[2:], "فلل" + form[2:]):
        return True
    return tok.endswith(form) and tok[:-len(form)] in _AR_PREFIX


def _pick(found: list[tuple[int, int, str]]) -> list[dict]:
    """Longest match wins where mentions overlap ("European Union" over "Europe")."""
    found.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    out, end = [], -1
    for s, e, k in found:
        if s >= end:
            out.append({"start": s, "end": e, "key": k})
            end = e
    return out


@lru_cache(maxsize=16)
def _find(text: str) -> tuple:
    if arabic.is_arabic(text):
        from .highlight import _ar_tokens
        toks = _ar_tokens(text)
        words = [t[2] for t in toks]
        found = []
        for i in range(len(words)):
            for form, key in _AR:
                n = len(form)
                if n and i + n <= len(words) and all(
                        _ar_token_is(words[i + j], form[j], j == 0) for j in range(n)):
                    found.append((toks[i][0], toks[i + n - 1][1], key))
                    break
        # Arabic text often quotes English names too.
        found += [(m.start(), m.end(), k) for rx, k in _EN for m in rx.finditer(text)]
    else:
        found = [(m.start(), m.end(), k) for rx, k in _EN for m in rx.finditer(text)]
    return tuple(tuple(d.items()) for d in _pick(found))


def find(text: str) -> list[dict]:
    """Every mention of a known country or organization: {start, end, key}."""
    # Offsets are Python code points, the same unit the highlighter uses.
    return [dict(d) for d in _find(text)]


def info(key: str) -> dict:
    e = ENTITIES[key]
    return {"key": key, "name": e["name"], "name_ar": e["name_ar"], "kind": e["kind"]}


def summarize(text: str, tones: dict | None = None, sentences: list[tuple[int, int]] | None = None) -> list[dict]:
    """Per country/organization: how often it is named, a tone per sentence, the sentences.

    `tones` maps (sentence index, key) to a tone set by the AI or a person; other
    sentences get the cue-word tone. Ordered by how often each is named.
    """
    from .context import sentences as split
    sents = sentences if sentences is not None else split(text)
    tones = tones or {}
    by_key: dict[str, dict] = {}
    si = 0
    for m in find(text):
        while si < len(sents) - 1 and m["start"] >= sents[si][1]:
            si += 1
        e = by_key.setdefault(m["key"], {**info(m["key"]), "count": 0, "statements": [], "_seen": set()})
        e["count"] += 1
        if si in e["_seen"]:
            continue
        e["_seen"].add(si)
        s, t = sents[si]
        sentence = text[s:t].strip()
        set_tone = tones.get((si, m["key"]))
        tone = set_tone["tone"] if set_tone else tone_of(sentence)[0]
        e["statements"].append({"sentence": si, "text": sentence, "tone": tone,
                                "source": set_tone["source"] if set_tone else "words"})
    out = []
    for e in by_key.values():
        e.pop("_seen")
        counts = {t: sum(1 for s in e["statements"] if s["tone"] == t)
                  for t in ("positive", "negative", "mixed", "neutral")}
        e["counts"] = counts
        e["tone"] = overall_tone(counts)
        out.append(e)
    return sorted(out, key=lambda e: -e["count"])


def overall_tone(counts: dict) -> str:
    pos, neg = counts.get("positive", 0), counts.get("negative", 0)
    if not pos and not neg:
        return "neutral"
    if pos and neg and min(pos, neg) * 2 >= max(pos, neg):
        return "mixed"
    return "positive" if pos > neg else "negative"
