"""World leaders on the panel: G20, G8 (the G7 plus Russia), BRICS+, the permanent
members of the UN Security Council, the Board of Peace (member countries' leaders and
its executive board), and the EU and African Union.

Each person is one record holding everything the app shows: the panel entry
(stakeholders._BUILTIN), the profile (dossier.PROFILES), the personality type, and
the Arabic text (stakeholders_ar.AR). The lists live in world_g20, world_bop and
world_board; this module joins them and adds the countries they need.

Where a country's head of state is ceremonial (a king or a president elected by
parliament), the person who runs the government is listed instead.
Office-holders checked November 2026; review them as roles change.
"""
from __future__ import annotations


def P(id, name, role, cc, category, country, personality, values, supports, opposes,
      concerns, responses, background, style, memberships, partners, frictions, ptype,
      ar, local=None, edition=("en", "US")):
    """One person. `cc` is the country's entity key; `ar` holds the same fields in Arabic
    (lists in the same order as the English, so partners keep their country links)."""
    return {"id": id, "name": name, "role": role, "cc": cc, "category": category,
            "country": country, "personality": personality, "values": values,
            "supports": supports, "opposes": opposes, "concerns": concerns,
            "responses": responses, "background": background, "style": style,
            "memberships": memberships, "partners": partners, "frictions": frictions,
            "ptype": ptype, "ar": ar, "local": local or name, "edition": edition}


# Countries the panel needs that the app did not know yet:
# key: (English name, Arabic name, English forms, Arabic forms), as in dossier.COUNTRIES.
# Albania and Australia get three-letter keys: "AL" and "AU" already mean the Arab
# League and the African Union.
COUNTRIES_EXTRA = {
    "AR": ("Argentina", "الأرجنتين", ["Argentina", "Argentine", "Argentinian", "Buenos Aires"],
           ["الأرجنتين", "الأرجنتيني"]),
    "AUS": ("Australia", "أستراليا", ["Australia", "Australian", "Canberra"], ["أستراليا", "الأسترالي"]),
    "ID": ("Indonesia", "إندونيسيا", ["Indonesia", "Indonesian", "Jakarta"], ["إندونيسيا", "الإندونيسي"]),
    "ALB": ("Albania", "ألبانيا", ["Albania", "Albanian", "Tirana"], ["ألبانيا", "الألباني"]),
    "AM": ("Armenia", "أرمينيا", ["Armenia", "Armenian", "Yerevan"], ["أرمينيا", "الأرميني"]),
    "BG": ("Bulgaria", "بلغاريا", ["Bulgaria", "Bulgarian"], ["بلغاريا", "البلغاري"]),
    "KH": ("Cambodia", "كمبوديا", ["Cambodia", "Cambodian", "Phnom Penh"], ["كمبوديا", "الكمبودي"]),
    "SV": ("El Salvador", "السلفادور", ["El Salvador", "Salvadoran"], ["السلفادور"]),
    "HU": ("Hungary", "المجر", ["Hungary", "Hungarian", "Budapest"], ["المجر", "المجري", "هنغاريا"]),
    "KZ": ("Kazakhstan", "كازاخستان", ["Kazakhstan", "Kazakh", "Astana"], ["كازاخستان", "الكازاخي"]),
    "XK": ("Kosovo", "كوسوفو", ["Kosovo", "Pristina"], ["كوسوفو"]),
    "MN": ("Mongolia", "منغوليا", ["Mongolia", "Mongolian", "Ulaanbaatar"], ["منغوليا", "المنغولي"]),
    "PY": ("Paraguay", "باراغواي", ["Paraguay", "Paraguayan", "Asunción", "Asuncion"], ["باراغواي"]),
    "UZ": ("Uzbekistan", "أوزبكستان", ["Uzbekistan", "Uzbek", "Tashkent"], ["أوزبكستان", "الأوزبكي"]),
    "VN": ("Vietnam", "فيتنام", ["Vietnam", "Viet Nam", "Vietnamese", "Hanoi"], ["فيتنام", "الفيتنامي"]),
    "SG": ("Singapore", "سنغافورة", ["Singapore", "Singaporean"], ["سنغافورة"]),
    "TH": ("Thailand", "تايلاند", ["Thailand", "Thai", "Bangkok"], ["تايلاند", "التايلاندي"]),
    "RS": ("Serbia", "صربيا", ["Serbia", "Serbian", "Belgrade"], ["صربيا", "الصربي"]),
    "TW": ("Taiwan", "تايوان", ["Taiwan", "Taiwanese", "Taipei"], ["تايوان", "التايواني"]),
    "BI": ("Burundi", "بوروندي", ["Burundi"], ["بوروندي"]),
    "DJ": ("Djibouti", "جيبوتي", ["Djibouti"], ["جيبوتي"]),
    "PL": ("Poland", "بولندا", ["Poland", "Polish", "Warsaw"], ["بولندا", "البولندي"]),
    "CO": ("Colombia", "كولومبيا", ["Colombia", "Colombian"], ["كولومبيا"]),
    # Moved here from entities.py so profiles can link to them too.

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
    "BY": ("Belarus", "بيلاروسيا", ["Belarus", "Belarusian", "Minsk"], ["بيلاروسيا"]),
    "AT": ("Austria", "النمسا", ["Austria", "Austrian", "Vienna"], ["النمسا", "النمساوي"]),
    "CU": ("Cuba", "كوبا", ["Cuba", "Cuban", "Havana"], ["كوبا", "الكوبي"]),
    "MK": ("North Macedonia", "مقدونيا الشمالية", ["North Macedonia", "Macedonian"], ["مقدونيا الشمالية"]),
}


def _people() -> list[dict]:
    from .world_g20 import PEOPLE as g20
    from .world_bop import PEOPLE as bop
    from .world_board import PEOPLE as board
    from .world_nonstate import PEOPLE as nonstate
    out, seen = [], set()
    for p in g20 + bop + board + nonstate:
        assert p["id"] not in seen, p["id"]
        seen.add(p["id"])
        out.append(p)
    return out


PEOPLE: list[dict] = _people()
CATEGORY = {p["id"]: p["category"] for p in PEOPLE}


def panel_entry(p: dict) -> dict:
    return {k: p[k] for k in ("id", "name", "role", "personality", "values", "supports",
                              "opposes", "concerns", "responses")} | {"scope": p["country"]}


def arabic(p: dict) -> dict:
    a = p["ar"]
    return {**a, "personality_type": a["ptype"]} if "ptype" in a else a
