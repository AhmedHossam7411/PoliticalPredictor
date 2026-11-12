"""Countries, organizations and places named in a speech, and how the speaker talks about them.

Places are continents, regions, seas (and rivers), straits, and trade routes, canals
and corridors.

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


# Places: key -> (English name, Arabic name, kind, English forms, Arabic forms).
# kind: continent, region, sea, strait, route (trade routes, canals and corridors).
_PLACES = {
    # Continents
    "C-AF": ("Africa", "أفريقيا", "continent", ["Africa", "African continent"], ["أفريقيا", "إفريقيا", "القارة الأفريقية", "القارة الإفريقية", "القارة السمراء"]),
    "C-AS": ("Asia", "آسيا", "continent", ["Asia", "Asian continent"], ["آسيا", "القارة الآسيوية"]),
    "C-EU": ("Europe", "أوروبا", "continent", ["Europe", "European continent"], ["أوروبا", "القارة الأوروبية", "القارة العجوز"]),
    "C-NA": ("North America", "أمريكا الشمالية", "continent", ["North America"], ["أمريكا الشمالية"]),
    "C-SA": ("South America", "أمريكا الجنوبية", "continent", ["South America"], ["أمريكا الجنوبية"]),
    "C-LA": ("Latin America", "أمريكا اللاتينية", "continent", ["Latin America"], ["أمريكا اللاتينية"]),
    "C-OC": ("Oceania", "أوقيانوسيا", "continent", ["Oceania"], ["أوقيانوسيا"]),
    "C-AN": ("Antarctica", "القارة القطبية الجنوبية", "continent", ["Antarctica"], ["القارة القطبية الجنوبية", "أنتاركتيكا"]),
    # Regions
    "R-ME": ("Middle East", "الشرق الأوسط", "region", ["Middle East", "MENA"], ["الشرق الأوسط"]),
    "R-HOA": ("Horn of Africa", "القرن الأفريقي", "region", ["Horn of Africa"], ["القرن الأفريقي", "القرن الإفريقي"]),
    "R-SAHEL": ("Sahel", "منطقة الساحل", "region", ["Sahel"], ["منطقة الساحل", "الساحل الأفريقي", "الساحل والصحراء"]),
    "R-LEV": ("Levant", "بلاد الشام", "region", ["Levant"], ["بلاد الشام", "المشرق العربي"]),
    "R-MAG": ("Maghreb", "المغرب العربي", "region", ["Maghreb", "North Africa"], ["المغرب العربي", "شمال أفريقيا", "شمال إفريقيا"]),
    "R-NILE": ("Nile Basin", "حوض النيل", "region", ["Nile Basin"], ["حوض النيل", "دول حوض النيل"]),
    "R-SINAI": ("Sinai", "سيناء", "region", ["Sinai"], ["سيناء", "شبه جزيرة سيناء"]),
    # Seas, oceans, gulfs and rivers
    "S-MED": ("Mediterranean Sea", "البحر المتوسط", "sea", ["Mediterranean Sea", "Mediterranean", "Eastern Mediterranean"],
              ["البحر المتوسط", "البحر الأبيض المتوسط", "شرق المتوسط", "حوض المتوسط"]),
    "S-RED": ("Red Sea", "البحر الأحمر", "sea", ["Red Sea"], ["البحر الأحمر"]),
    "S-BLACK": ("Black Sea", "البحر الأسود", "sea", ["Black Sea"], ["البحر الأسود"]),
    "S-CASP": ("Caspian Sea", "بحر قزوين", "sea", ["Caspian Sea", "Caspian"], ["بحر قزوين"]),
    "S-ARAB": ("Arabian Sea", "بحر العرب", "sea", ["Arabian Sea"], ["بحر العرب"]),
    "S-GULF": ("Arabian (Persian) Gulf", "الخليج العربي", "sea", ["Arabian Gulf", "Persian Gulf"], ["الخليج العربي", "الخليج الفارسي"]),
    "S-ADEN": ("Gulf of Aden", "خليج عدن", "sea", ["Gulf of Aden"], ["خليج عدن"]),
    "S-OMAN": ("Gulf of Oman", "خليج عمان", "sea", ["Gulf of Oman"], ["خليج عمان"]),
    "S-SUEZG": ("Gulf of Suez", "خليج السويس", "sea", ["Gulf of Suez"], ["خليج السويس"]),
    "S-AQABA": ("Gulf of Aqaba", "خليج العقبة", "sea", ["Gulf of Aqaba", "Gulf of Eilat"], ["خليج العقبة"]),
    "S-AEGEAN": ("Aegean Sea", "بحر إيجه", "sea", ["Aegean Sea", "Aegean"], ["بحر إيجه"]),
    "S-ATL": ("Atlantic Ocean", "المحيط الأطلسي", "sea", ["Atlantic Ocean", "Atlantic"], ["المحيط الأطلسي", "المحيط الأطلنطي"]),
    "S-IND": ("Indian Ocean", "المحيط الهندي", "sea", ["Indian Ocean"], ["المحيط الهندي"]),
    "S-PAC": ("Pacific Ocean", "المحيط الهادئ", "sea", ["Pacific Ocean", "Pacific", "Indo-Pacific"], ["المحيط الهادئ", "المحيط الهادي", "المحيطين الهندي والهادئ"]),
    "S-ARCTIC": ("Arctic", "القطب الشمالي", "sea", ["Arctic", "Arctic Ocean"], ["القطب الشمالي", "المحيط المتجمد الشمالي"]),
    "S-SCS": ("South China Sea", "بحر الصين الجنوبي", "sea", ["South China Sea"], ["بحر الصين الجنوبي"]),
    "S-BALTIC": ("Baltic Sea", "بحر البلطيق", "sea", ["Baltic Sea", "Baltic"], ["بحر البلطيق"]),
    "S-NILE": ("Nile", "نهر النيل", "sea", ["Nile", "River Nile", "Nile River", "Blue Nile"], ["نهر النيل", "النيل", "النيل الأزرق"]),
    "S-EUPH": ("Euphrates and Tigris", "دجلة والفرات", "sea", ["Euphrates", "Tigris"], ["الفرات", "دجلة", "نهر الفرات", "نهر دجلة"]),
    # Straits
    "T-HORMUZ": ("Strait of Hormuz", "مضيق هرمز", "strait", ["Strait of Hormuz", "Hormuz"], ["مضيق هرمز", "هرمز"]),
    "T-BAB": ("Bab el-Mandeb", "باب المندب", "strait", ["Bab el-Mandeb", "Bab al-Mandab", "Bab-el-Mandeb"], ["باب المندب", "مضيق باب المندب"]),
    "T-GIB": ("Strait of Gibraltar", "مضيق جبل طارق", "strait", ["Strait of Gibraltar", "Gibraltar"], ["مضيق جبل طارق", "جبل طارق"]),
    "T-BOSP": ("Bosphorus", "مضيق البوسفور", "strait", ["Bosphorus", "Bosporus", "Turkish Straits"], ["مضيق البوسفور", "البوسفور", "المضائق التركية"]),
    "T-DARD": ("Dardanelles", "مضيق الدردنيل", "strait", ["Dardanelles"], ["مضيق الدردنيل", "الدردنيل"]),
    "T-MALACCA": ("Strait of Malacca", "مضيق ملقا", "strait", ["Strait of Malacca", "Malacca Strait"], ["مضيق ملقا", "مضيق ملقة"]),
    "T-TAIWAN": ("Taiwan Strait", "مضيق تايوان", "strait", ["Taiwan Strait"], ["مضيق تايوان"]),
    "T-TIRAN": ("Strait of Tiran", "مضيق تيران", "strait", ["Strait of Tiran", "Straits of Tiran", "Tiran"], ["مضيق تيران", "تيران"]),
    # Trade routes, canals and corridors
    "W-SUEZ": ("Suez Canal", "قناة السويس", "route", ["Suez Canal", "Suez"], ["قناة السويس"]),
    "W-SCZONE": ("Suez Canal Economic Zone", "المنطقة الاقتصادية لقناة السويس", "route", ["Suez Canal Economic Zone", "SCZone"],
                 ["المنطقة الاقتصادية لقناة السويس"]),
    "W-PANAMA": ("Panama Canal", "قناة بنما", "route", ["Panama Canal"], ["قناة بنما"]),
    "W-BRI": ("Belt and Road Initiative", "مبادرة الحزام والطريق", "route",
              ["Belt and Road Initiative", "Belt and Road", "BRI", "New Silk Road"], ["مبادرة الحزام والطريق", "الحزام والطريق", "طريق الحرير الجديد"]),
    "W-SILK": ("Silk Road", "طريق الحرير", "route", ["Silk Road"], ["طريق الحرير"]),
    "W-IMEC": ("India–Middle East–Europe Economic Corridor", "الممر الاقتصادي الهند-الشرق الأوسط-أوروبا", "route",
               ["India-Middle East-Europe Economic Corridor", "India–Middle East–Europe Economic Corridor", "IMEC"],
               ["الممر الاقتصادي بين الهند والشرق الأوسط وأوروبا", "الممر الاقتصادي الهندي", "ممر الهند والشرق الأوسط وأوروبا"]),
    "W-INSTC": ("International North–South Transport Corridor", "ممر النقل الدولي بين الشمال والجنوب", "route",
                ["North-South Transport Corridor", "North–South Transport Corridor", "INSTC"], ["ممر الشمال والجنوب", "ممر النقل بين الشمال والجنوب"]),
    "W-DEVROAD": ("Development Road (Iraq)", "طريق التنمية", "route", ["Development Road"], ["طريق التنمية"]),
    "W-ZANG": ("Zangezur Corridor", "ممر زنغزور", "route", ["Zangezur Corridor", "Zangezur"], ["ممر زنغزور", "ممر زنكزور"]),
    "W-PHILA": ("Philadelphi Corridor", "محور فيلادلفيا", "route", ["Philadelphi Corridor", "Philadelphi Route", "Philadelphi"],
                ["محور فيلادلفيا", "ممر فيلادلفيا", "محور صلاح الدين"]),
    "W-NETZ": ("Netzarim Corridor", "محور نتساريم", "route", ["Netzarim Corridor", "Netzarim"], ["محور نتساريم", "ممر نتساريم"]),
    "W-RAFAH": ("Rafah Crossing", "معبر رفح", "route", ["Rafah Crossing", "Rafah border crossing"], ["معبر رفح"]),
    "W-LOBITO": ("Lobito Corridor", "ممر لوبيتو", "route", ["Lobito Corridor"], ["ممر لوبيتو"]),
    "W-NSR": ("Northern Sea Route", "طريق البحر الشمالي", "route", ["Northern Sea Route"], ["طريق البحر الشمالي"]),
    "W-CAPE": ("Cape of Good Hope route", "رأس الرجاء الصالح", "route", ["Cape of Good Hope"], ["رأس الرجاء الصالح"]),
    "W-SUMED": ("SUMED pipeline", "خط سوميد", "route", ["SUMED", "Sumed pipeline"], ["خط سوميد", "سوميد"]),
    "W-EASTMED": ("EastMed Gas Forum", "منتدى غاز شرق المتوسط", "route", ["East Mediterranean Gas Forum", "EastMed Gas Forum", "EMGF"],
                  ["منتدى غاز شرق المتوسط"]),
}

ENTITIES: dict[str, dict] = {}
for _k, (_en, _ar, _ef, _af) in {**COUNTRIES, **_EXTRA_COUNTRIES}.items():
    ENTITIES[_k] = {"name": _en, "name_ar": _ar, "kind": "organization" if _k == "EU" else "country",
                    "en": _ef, "ar": _af}
for _k, (_en, _ar, _ef, _af) in _ORGS.items():
    ENTITIES[_k] = {"name": _en, "name_ar": _ar, "kind": "organization", "en": _ef, "ar": _af}
# "Palestine" lists "the occupation" for headlines; in a speech that names Israel.
ENTITIES["IL"]["ar"] = [f for f in ENTITIES["IL"]["ar"] if f != "الاحتلال"]
for _k, (_en, _ar, _kind, _ef, _af) in _PLACES.items():
    ENTITIES[_k] = {"name": _en, "name_ar": _ar, "kind": _kind, "en": _ef, "ar": _af}
# In a speech "Europe" is the continent; the European Union keeps its own names.
ENTITIES["EU"]["en"] = ["European Union", "EU", "E.U."]
ENTITIES["EU"]["ar"] = ["الاتحاد الأوروبي", "الاتحاد الاوروبي"]
ENTITIES["C-EU"]["en"] += ["European"]
ENTITIES["C-AF"]["en"] += ["African"]
ENTITIES["C-AS"]["en"] += ["Asian"]


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
