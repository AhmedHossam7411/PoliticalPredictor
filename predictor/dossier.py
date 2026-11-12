"""Stakeholder profiles: who the person is, how they lead, who they stand with, and
what trusted outlets are reporting about them, inside their country first, then abroad.

Two layers:
  * PROFILES: a compiled summary of each built-in stakeholder's public record
    (background, personality type, leadership style, memberships, partners, points of
    friction) with links to their official sites. Written November 2026; review as
    roles change.
  * Live coverage from Google News, kept only when the outlet is on a trusted list:
    the person's own country's outlets first, then international ones, then speeches.
    Cached for an hour. No AI is involved in either layer.

`mentions` lists the person's speeches that touched on one partner or rival country,
from trusted outlets' reports: date, place and tone (see that function).
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import httpx

CACHE_SECONDS = 3600
TIMEOUT = 12.0
MAX_ITEMS = 8
_cache: dict[str, tuple[float, dict]] = {}

# --------------------------------------------------------------------------- #
# Trusted outlets. Domestic lists are each country's established media and
# official sources; anything not listed is left out.
# --------------------------------------------------------------------------- #
DOMESTIC = {
    "EG": ["ahram.org.eg", "youm7.com", "almasryalyoum.com", "egyptindependent.com",
           "shorouknews.com", "masrawy.com", "elwatannews.com", "akhbarelyom.com",
           "egypttoday.com", "dailynewsegypt.com", "madamasr.com", "alwafd.news",
           "elbalad.news", "sis.gov.eg", "presidency.eg", "cabinet.gov.eg", "mfa.gov.eg",
           "cbe.org.eg", "mena.org.eg", "maspero.eg", "almalnews.com", "enterprise.press",
           "wataninet.com", "azhar.eg"],
    "SA": ["spa.gov.sa", "arabnews.com", "aawsat.com", "alarabiya.net", "saudigazette.com.sa",
           "okaz.com.sa", "alriyadh.com", "alwatan.com.sa", "aleqt.com", "sabq.org", "asharq.com"],
    "AE": ["wam.ae", "thenationalnews.com", "khaleejtimes.com", "gulfnews.com",
           "skynewsarabia.com", "alkhaleej.ae", "albayan.ae", "emaratalyoum.com", "alittihad.ae"],
    "QA": ["qna.org.qa", "aljazeera.com", "aljazeera.net", "thepeninsulaqatar.com",
           "gulf-times.com", "al-sharq.com", "raya.com", "alwatan.com.qa", "diwan.gov.qa",
           "mofa.gov.qa"],
    "JO": ["petra.gov.jo", "jordantimes.com", "alghad.com", "alrai.com", "addustour.com",
           "royanews.tv", "almamlakatv.com", "ammonnews.net", "rhc.jo", "kingabdullah.jo",
           "jordannews.jo"],
    "TR": ["aa.com.tr", "dailysabah.com", "hurriyetdailynews.com", "trtworld.com",
           "trthaber.com", "hurriyet.com.tr", "sabah.com.tr", "milliyet.com.tr", "ntv.com.tr",
           "sozcu.com.tr", "cumhuriyet.com.tr", "bianet.org", "medyascope.tv",
           "iletisim.gov.tr", "tccb.gov.tr", "bloomberght.com", "t24.com.tr"],
    "IL": ["timesofisrael.com", "haaretz.com", "haaretz.co.il", "jpost.com", "ynetnews.com",
           "ynet.co.il", "israelhayom.com", "israelhayom.co.il", "i24news.tv", "kan.org.il",
           "gov.il", "maariv.co.il", "globes.co.il", "davar1.co.il", "n12.co.il", "mako.co.il"],
    "IR": ["irna.ir", "isna.ir", "tasnimnews.com", "mehrnews.com", "farsnews.ir", "presstv.ir",
           "tehrantimes.com", "president.ir", "khamenei.ir", "mfa.ir", "hamshahrionline.ir",
           "tabnak.ir", "entekhab.ir", "khabaronline.ir", "ilna.ir", "ana.ir",
           "donya-e-eqtesad.com", "etemadonline.com", "shargdaily.com", "ifpnews.com"],
    "PS": ["wafa.ps", "maannews.net", "alquds.com", "al-ayyam.ps", "wattan.net",
           "palestine.ps", "yaffaps.com"],
    "SY": ["sana.sy", "enabbaladi.net", "alwatan.sy", "syria.tv", "verify-sy.com",
           "aliqtisadi.com"],
    "LB": ["annahar.com", "lbcgroup.tv", "almodon.com", "elnashra.com", "nna-leb.gov.lb",
           "naharnet.com", "lorientlejour.com"],
}
# Long-established international outlets and wire services.
INTERNATIONAL = ["reuters.com", "apnews.com", "afp.com", "bbc.com", "bbc.co.uk",
                 "theguardian.com", "ft.com", "nytimes.com", "washingtonpost.com", "wsj.com",
                 "economist.com", "bloomberg.com", "france24.com", "dw.com", "npr.org",
                 "cnn.com", "euronews.com", "lemonde.fr", "politico.com", "politico.eu",
                 "foreignpolicy.com", "foreignaffairs.com", "axios.com", "cnbc.com",
                 "voanews.com", "rfi.fr", "mc-doualiya.com", "independent.co.uk",
                 "aljazeera.com", "aljazeera.net", "alarabiya.net", "aawsat.com",
                 "skynewsarabia.com", "thenationalnews.com", "arabnews.com", "middleeasteye.net",
                 "al-monitor.com", "annahar.com", "lorientlejour.com", "timesofisrael.com",
                 "haaretz.com", "aa.com.tr", "trtworld.com", "dailysabah.com", "ahram.org.eg",
                 "egyptindependent.com", "jordantimes.com", "tehrantimes.com", "presstv.ir"]

# Where a Google News search is run: (language, country edition) for local searches.
_EDITIONS = {"EG": ("ar", "EG"), "SA": ("ar", "SA"), "AE": ("ar", "AE"), "QA": ("ar", "SA"),
             "JO": ("ar", "SA"), "PS": ("ar", "LB"), "SY": ("ar", "LB"), "LB": ("ar", "LB"),
             "TR": ("tr", "TR"), "IL": ("he", "IL"), "IR": ("ar", "SA")}
_SPEECH_WORDS = {"ar": "كلمة OR خطاب", "tr": "konuşma OR hitap", "he": "נאום",
                 "en": "speech OR address OR remarks"}


# A headline counts as a speech only if it says so ("كلمة السر" is not a speech).
_SPEECH_TITLE = re.compile(
    r"\b(speech|speeches|address(es|ed)?|remarks|told the|tells the)\b|"
    r"كلمته|كلمة (الرئيس|الملك|الأمير|ولي|البابا|شيخ|الإمام|رئيس|وزير|محافظ|أمام|في|خلال|مسجلة)|"
    r"خطاب|يلقي|ألقى|ألقاها|أمام (الأمم|الجمعية|مجلس|البرلمان|الكنيست|القمة)|"
    r"konuşma|hitap|נאום|נאם", re.IGNORECASE)


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _on(domain: str, sites) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in sites)


def outlet_country(domain: str) -> str | None:
    """The country a trusted outlet is based in, or None if it isn't trusted."""
    for cc, sites in DOMESTIC.items():
        if _on(domain, sites):
            return cc
    return "INTL" if _on(domain, INTERNATIONAL) else None


# --------------------------------------------------------------------------- #
# Compiled profiles of the built-in stakeholders.
# --------------------------------------------------------------------------- #
def _p(country, cc, local, local_query, official, background, style,
       memberships, partners, frictions):
    return {"country": country, "cc": cc, "name_local": local, "query_local": local_query,
            "official": [{"name": n, "url": u} for n, u in official],
            "background": background, "leadership_style": style,
            "memberships": memberships, "partners": partners, "frictions": frictions}


PROFILES: dict[str, dict] = {
    "sisi": _p(
        "Egypt", "EG", "عبد الفتاح السيسي", '"السيسي"', [("Presidency of Egypt", "https://www.presidency.eg"),
         ("State Information Service", "https://www.sis.gov.eg")],
        "Career army officer; head of military intelligence, then defence minister from 2012. "
        "Led the armed forces when President Mohamed Morsi was removed in July 2013 after mass "
        "protests. President since 2014; re-elected in 2018 and 2023.",
        "Centralised and security-first. Presents stability and state-led development (new "
        "cities, roads, the Suez Canal expansion) as the basis of national strength, and often "
        "speaks to citizens directly about patience and sacrifice during economic reform. In "
        "foreign policy a cautious balancer, keeping ties with the US, the Gulf, Europe, Russia "
        "and China at the same time.",
        ["Arab League (headquarters in Cairo)", "African Union", "BRICS (since 2024)",
         "Organisation of Islamic Cooperation", "Non-Aligned Movement",
         "East Mediterranean Gas Forum (founding member)"],
        ["Saudi Arabia", "United Arab Emirates", "United States", "European Union", "China",
         "Russia", "Jordan"],
        ["Ethiopia (the Nile dam, GERD)", "The war in Sudan on Egypt's border",
         "Instability in Libya", "Israel over Gaza and the Rafah crossing"]),
    "mbs": _p(
        "Saudi Arabia", "SA", "محمد بن سلمان", '"محمد بن سلمان"', [("Saudi Press Agency", "https://www.spa.gov.sa"),
         ("Vision 2030", "https://www.vision2030.gov.sa")],
        "Son of King Salman. Crown prince since 2017 and prime minister since 2022, running the "
        "government day to day. Leads Vision 2030, the plan to diversify the economy away from oil.",
        "Fast, top-down and ambitious. Has centralised power and pushed rapid social and economic "
        "change: giga-projects such as NEOM, opening up tourism and entertainment, allowing women "
        "to drive. Uses Saudi financial and oil weight as foreign-policy leverage, and has moved "
        "from confrontation in the region toward de-escalation and deal-making.",
        ["Gulf Cooperation Council", "Arab League", "OPEC and OPEC+ (leading role)", "G20",
         "Organisation of Islamic Cooperation (headquarters in Jeddah)",
         "Invited to BRICS in 2023; membership not confirmed"],
        ["United States", "United Arab Emirates", "Egypt", "China", "Pakistan",
         "Russia (oil policy through OPEC+)"],
        ["Iran (relations restored in 2023 under a China-brokered deal; rivalry remains)",
         "The Houthis in Yemen", "Israel (normalisation tied to a path to a Palestinian state)"]),
    "mbz": _p(
        "United Arab Emirates", "AE", "محمد بن زايد", '"محمد بن زايد"', [("Emirates News Agency (WAM)", "https://www.wam.ae")],
        "Long the UAE's de facto leader as crown prince of Abu Dhabi; president of the UAE since "
        "May 2022. Built up the UAE's armed forces.",
        "Strategic, security-minded and pragmatic. Treats political Islamist movements as a core "
        "threat. Projects UAE influence through investment, ports and logistics, technology and "
        "military partnerships, and is willing to break with regional consensus, as with the 2020 "
        "Abraham Accords with Israel.",
        ["Gulf Cooperation Council", "Arab League", "OPEC", "BRICS (since 2024)",
         "Organisation of Islamic Cooperation", "Abraham Accords (2020)"],
        ["Saudi Arabia", "Egypt", "United States", "France", "India", "China", "Israel (since 2020)"],
        ["Political Islamist groups such as the Muslim Brotherhood",
         "Iran-backed groups, including the Houthis",
         "The war in Sudan (accused of backing the RSF, which the UAE denies)"]),
    "tamim": _p(
        "Qatar", "QA", "تميم بن حمد", '"تميم بن حمد"', [("Amiri Diwan", "https://www.diwan.gov.qa"), ("Qatar News Agency", "https://www.qna.org.qa"),
         ("Ministry of Foreign Affairs", "https://www.mofa.gov.qa")],
        "Became emir in 2013 when his father, Sheikh Hamad, handed over power. Led Qatar through "
        "the 2017–2021 blockade by Saudi Arabia, the UAE, Bahrain and Egypt, and hosted the 2022 "
        "FIFA World Cup.",
        "Calm, low-key and consensus-seeking in public. Runs an independent foreign policy that "
        "keeps channels open to rivals, which makes Qatar a go-to mediator (Gaza, Afghanistan, "
        "prisoner exchanges). Relies on gas wealth and soft power, including the state-funded "
        "Al Jazeera network.",
        ["Gulf Cooperation Council", "Arab League", "Organisation of Islamic Cooperation",
         "Gas Exporting Countries Forum (headquarters in Doha)", "Major non-NATO ally of the US (2022)"],
        ["Turkey", "United States (Al Udeid air base)", "Kuwait", "Oman",
         "Iran (working relations, shared gas field)"],
        ["The 2017–2021 blockading states (since reconciled)", "Israel over Gaza",
         "Criticism of its ties with Hamas and the Muslim Brotherhood"]),
    "abdullah-ii": _p(
        "Jordan", "JO", "الملك عبدالله الثاني", '"الملك عبدالله الثاني"', [("King Abdullah II (official site)", "https://kingabdullah.jo"),
         ("Royal Hashemite Court", "https://rhc.jo"), ("Petra News Agency", "https://petra.gov.jo")],
        "King since 1999, succeeding his father King Hussein. Trained at Sandhurst and commanded "
        "Jordan's special forces. Custodian of the Muslim and Christian holy sites in Jerusalem.",
        "Measured, Western-educated diplomat who speaks easily to Western audiences. Positions "
        "Jordan as a moderate, stable partner and a leading voice for a two-state solution. "
        "Cautious at home, balancing reform plans against security and economic pressure.",
        ["Arab League", "Organisation of Islamic Cooperation", "Major non-NATO ally of the US",
         "Peace treaty with Israel (1994)"],
        ["United States", "United Kingdom", "Egypt", "Saudi Arabia", "European Union", "Iraq"],
        ["The Israeli government over the West Bank and Al-Aqsa",
         "The burden of hosting refugees", "Smuggling across the Syrian border"]),
    "erdogan": _p(
        "Turkey", "TR", "Recep Tayyip Erdoğan", '"Erdoğan"', [("Presidency of Türkiye", "https://www.tccb.gov.tr"),
         ("Anadolu Agency", "https://www.aa.com.tr"), ("Ministry of Foreign Affairs", "https://www.mfa.gov.tr")],
        "Mayor of Istanbul in the 1990s; co-founded the AK Party in 2001. Prime minister "
        "2003–2014 and president since 2014; a 2017 referendum created an executive presidency. "
        "Re-elected in 2023.",
        "Combative, populist speaker who often frames politics as the nation against its "
        "enemies and criticises the West. Pragmatic in practice: shifts alignments when interests "
        "change, combining NATO membership with ties to Russia and the Gulf. Keeps strong "
        "personal control over policy.",
        ["NATO", "G20", "Council of Europe", "Organisation of Islamic Cooperation",
         "Organization of Turkic States", "EU candidate (talks frozen)"],
        ["Qatar", "Azerbaijan", "Syria's new government", "Pakistan",
         "Russia (energy and trade, despite opposing sides in some conflicts)"],
        ["Israel over Gaza", "Kurdish militant groups (PKK, YPG)",
         "Greece (Eastern Mediterranean)", "Cyprus",
         "United States (rights, defence purchases)", "European Union (frozen membership talks)"]),
    "netanyahu": _p(
        "Israel", "IL", "בנימין נתניהו", '"נתניהו"', [("Prime Minister's Office", "https://www.gov.il/en/departments/prime_ministers_office")],
        "Israel's longest-serving prime minister (1996–1999, 2009–2021 and since December 2022) "
        "and leader of Likud. On trial on corruption charges, which he denies. Led Israel through "
        "the war that began on 7 October 2023. The October 2026 election gave no bloc a majority; "
        "coalition talks were under way in November 2026.",
        "Security-first and a skilled communicator, especially to American audiences. Frames Iran "
        "as the central threat. Opposes a Palestinian state and pursues normalisation with Arab "
        "states. Known as a political survivor who manages coalition partners closely.",
        ["OECD", "Abraham Accords (2020)", "Major non-NATO ally of the US"],
        ["United States", "United Arab Emirates", "Bahrain", "Morocco", "Germany", "India"],
        ["Iran and its allies (Hezbollah, Hamas, the Houthis)", "The Palestinian Authority",
         "Turkey", "International Criminal Court (arrest warrant, 2024)", "UN bodies"]),
    "pezeshkian": _p(
        "Iran", "IR", "مسعود پزشکیان", '"پزشکیان"', [("Office of the President", "https://president.ir"), ("IRNA", "https://en.irna.ir"),
         ("Ministry of Foreign Affairs", "https://mfa.ir")],
        "Heart surgeon, health minister 2001–2005 and a long-serving member of parliament for "
        "Tabriz. Elected president in July 2024 as the reformist-backed candidate.",
        "Plain-spoken and conciliatory; favours national unity, talks with the West and better "
        "ties with neighbours. Works within the system: the Supreme Leader (Mojtaba Khamenei since "
        "March 2026) and the security bodies decide nuclear and security policy.",
        ["BRICS (since 2024)", "Shanghai Cooperation Organisation (since 2023)", "OPEC",
         "Organisation of Islamic Cooperation"],
        ["Russia", "China", "Iraq", "Allied armed groups in the region (the 'Axis of Resistance')"],
        ["Israel (wars in 2025 and 2026)", "United States (strikes and sanctions)",
         "Western governments over the nuclear programme"]),
    "abbas": _p(
        "Palestine", "PS", "محمود عباس", '"محمود عباس"', [("WAFA News Agency", "https://english.wafa.ps")],
        "Co-founder of Fatah and a PLO negotiator in the Oslo process. Elected president of the "
        "Palestinian Authority in 2005 and also chairs the PLO. No presidential election has been "
        "held since; he has announced one for early 2027.",
        "Cautious and legalistic; committed to diplomacy and non-violent resistance, seeking "
        "statehood through the UN, international courts and recognition by other states. Opposes "
        "Hamas rule in Gaza. Faces low popularity at home and open questions about succession.",
        ["Arab League (State of Palestine)", "Organisation of Islamic Cooperation",
         "UN non-member observer state (since 2012)", "International Criminal Court (member since 2015)"],
        ["Egypt", "Jordan", "Saudi Arabia", "European Union",
         "France (recognised Palestine in 2025)", "United Kingdom (recognised Palestine in 2025)"],
        ["The Israeli government", "Hamas", "The US administration over recognition"]),
    "sharaa": _p(
        "Syria", "SY", "أحمد الشرع", '"أحمد الشرع"', [("SANA News Agency", "https://sana.sy")],
        "Formerly known as Abu Mohammad al-Jolani, leader of Hayat Tahrir al-Sham, which led the "
        "offensive that toppled Bashar al-Assad in December 2024. Named interim president in "
        "January 2025.",
        "Has recast himself from armed commander to statesman, speaking of national unity, "
        "reconstruction and ending Syria's isolation. Pragmatic with foreign powers, courting the "
        "Gulf, Turkey and the West for sanctions relief and investment.",
        ["Arab League", "Organisation of Islamic Cooperation"],
        ["Turkey", "Saudi Arabia", "Qatar", "United Arab Emirates", "United States (sanctions eased in 2025)"],
        ["Israel (strikes and troops in southern Syria)", "Iran and Hezbollah",
         "The Kurdish-led SDF over integration", "Remaining extremist groups"]),
    "madbouly": _p(
        "Egypt", "EG", "مصطفى مدبولي", '"مدبولي"', [("Egyptian Cabinet", "https://www.cabinet.gov.eg")],
        "Urban planner and former housing minister. Prime minister since June 2018; Parliament "
        "approved his reshuffled cabinet in February 2026.",
        "Technocratic, detail-focused manager. The government's main voice on prices, subsidies, "
        "investment and the IMF programme, with frequent press conferences and site visits.",
        ["Egyptian government (prime minister)"],
        ["Gulf investors (including the UAE's Ras El Hekma deal, 2024)", "IMF and World Bank",
         "European Union"],
        ["Inflation and pressure on the pound", "Public frustration over prices"]),
    "abdelatty": _p(
        "Egypt", "EG", "بدر عبد العاطي", '"عبد العاطي"', [("Ministry of Foreign Affairs", "https://www.mfa.gov.eg")],
        "Career diplomat and former ambassador to Germany. Foreign minister since July 2024, also "
        "responsible for international cooperation and Egyptians abroad.",
        "Energetic, hands-on diplomat with a heavy schedule of calls and visits; central to "
        "Egypt's mediation on Gaza and its positions on Sudan, Libya and the Nile.",
        ["Egyptian government (foreign minister)", "Egypt's governor at the World Bank (2026)"],
        ["Saudi Arabia", "United Arab Emirates", "Qatar", "United States", "European Union"],
        ["Ethiopia over the Nile dam", "Israel over Gaza and the Rafah crossing"]),
    "hassan-abdalla": _p(
        "Egypt", "EG", "حسن عبد الله", '"حسن عبد الله" البنك المركزي', [("Central Bank of Egypt", "https://www.cbe.org.eg")],
        "Banker and former head of the Arab African International Bank. Governor of the Central "
        "Bank of Egypt since 2022 and Egypt's governor at the IMF.",
        "Low-profile and technical; speaks mostly through monetary-policy statements. Oversaw the "
        "March 2024 move to a flexible exchange rate and sharp interest-rate rises to bring "
        "inflation down.",
        ["Central Bank of Egypt (governor)", "IMF Board of Governors (for Egypt)"],
        ["IMF", "Gulf central banks and investors"],
        ["Inflation", "Foreign-currency shortages"]),
    "el-tayeb": _p(
        "Egypt", "EG", "أحمد الطيب", '"شيخ الأزهر"', [("Al-Azhar", "https://www.azhar.eg")],
        "Islamic philosopher with a doctorate from the Sorbonne; former president of Al-Azhar "
        "University and Grand Mufti of Egypt. Grand Imam of Al-Azhar since 2010.",
        "Soft-spoken scholar who guards Al-Azhar's independence on religious questions. Champions "
        "moderate Islam and interfaith dialogue, notably the 2019 Document on Human Fraternity "
        "signed with Pope Francis. Speaks out strongly on Gaza and Jerusalem.",
        ["Al-Azhar (Grand Imam)", "Muslim Council of Elders (chair)"],
        ["The Catholic Church (Document on Human Fraternity, 2019)", "The Coptic Orthodox Church",
         "Egyptian state institutions"],
        ["Extremist groups", "Occasional public differences with the government over religious discourse"]),
    "tawadros": _p(
        "Egypt", "EG", "البابا تواضروس الثاني", '"البابا تواضروس"', [("Coptic Orthodox Church", "https://copticorthodox.church")],
        "Pharmacist before becoming a monk; Coptic Orthodox Pope of Alexandria since November "
        "2012, leading the largest Christian community in the Middle East.",
        "Pastoral and conciliatory; stresses national unity and support for the Egyptian state, "
        "and keeps close ties with Al-Azhar. Avoids partisan politics while pressing for church "
        "building and Copts' rights.",
        ["Coptic Orthodox Church (Pope)", "World Council of Churches (member church)",
         "Middle East Council of Churches"],
        ["Al-Azhar", "The Egyptian state", "The Catholic Church and other churches"],
        ["Sectarian attacks on Copts", "Slow church-building permits"]),
    "sawiris": _p(
        "Egypt", "EG", "نجيب ساويرس", '"نجيب ساويرس"', [("Orascom Investment Holding", "https://www.orascomih.com")],
        "Eldest son of Onsi Sawiris, founder of Orascom. Built Orascom Telecom into a regional "
        "mobile operator, and now invests in telecoms, media, gold mining and property (Ora "
        "Developers). Co-founded the Free Egyptians Party in 2011.",
        "Outspoken, liberal and pro-market; comments bluntly on economic policy on TV and social "
        "media, often calling for a smaller state role in business.",
        ["Orascom Investment Holding", "Ora Developers", "Free Egyptians Party (co-founder, 2011)"],
        ["Private-sector and international investors"],
        ["State-owned companies competing with private business", "Islamist politics"]),
}


# --------------------------------------------------------------------------- #
# Live coverage
# --------------------------------------------------------------------------- #
def _news(query: str, hl: str, gl: str, days: int = 30) -> list[dict]:
    """Google News search results (newest first)."""
    url = (f"https://news.google.com/rss/search?q={quote(query + f' when:{days}d')}"
           f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 PoliticalPredictor/1.0"},
                     timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    items = []
    for it in ET.fromstring(resp.content).iter("item"):
        src = it.find("source")
        source_url = src.get("url", "") if src is not None else ""
        title = (it.findtext("title") or "").strip()
        name = (src.text or "").strip() if src is not None else ""
        if name and title.endswith(" - " + name):
            title = title[: -len(name) - 3]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            published = ""
        items.append({"title": title, "url": it.findtext("link") or "", "source": name,
                      "domain": _domain(source_url), "published": published})
    return items


def _pick(items: list[dict], keep) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        key = re.sub(r"\W+", "", it["title"].lower())[:80]
        if key in seen or not keep(it["domain"]):
            continue
        seen.add(key)
        out.append(it)
    return out[:MAX_ITEMS]


def build(person: dict, language: str = "en") -> dict:
    """The full profile for one panel entry (see the module docstring)."""
    sid = person["id"]
    key = f"{sid}:{language}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    prof = PROFILES.get(sid)
    cc = prof["cc"] if prof else None
    home = DOMESTIC.get(cc, [])
    hl, gl = _EDITIONS.get(cc, ("ar", "EG"))
    en_q = f'"{person["name"]}"'
    local_q = prof["query_local"] if prof else en_q
    jobs = {
        "local": lambda: _news(local_q, hl, gl),
        "english": lambda: _news(en_q, "en", "US"),
        "speech_local": lambda: _news(f"{local_q} ({_SPEECH_WORDS.get(hl, '')})", hl, gl, 180),
        "speech_en": lambda: _news(f"{en_q} ({_SPEECH_WORDS['en']})", "en", "US", 180),
    }
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(f) for k, f in jobs.items()}
        for k, fut in futures.items():
            try:
                results[k] = fut.result()
            except (httpx.HTTPError, ET.ParseError, KeyError, ValueError) as exc:
                results[k] = []
                errors.append(f"{k}: {type(exc).__name__}")

    is_home = (lambda d: _on(d, home)) if home else (lambda d: False)
    trusted_abroad = lambda d: (oc := outlet_country(d)) is not None and not is_home(d) and oc != cc
    trusted = lambda d: outlet_country(d) is not None
    news = {
        "domestic": _pick(results["local"] + results["english"], is_home) if home else [],
        "international": _pick(results["english"] + results["local"], trusted_abroad if home else trusted),
        "speeches": _pick([it for it in results["speech_local"] + results["speech_en"]
                           if _SPEECH_TITLE.search(it["title"])], trusted),
    }
    out = {
        "id": sid, "profile": _with_details(sid, prof) if prof else None,
        "news": news, "errors": errors,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not errors:
        _cache[key] = (time.time(), out)
    return out


# --------------------------------------------------------------------------- #
# Personality type, name forms used in headlines, and clickable countries
# --------------------------------------------------------------------------- #
PERSONALITY = {
    "sisi": ["Security-first", "Centralised decision-maker", "Cautious balancer", "Developmentalist"],
    "mbs": ["Ambitious moderniser", "Top-down", "Risk-taker", "Deal-maker"],
    "mbz": ["Strategic", "Security-minded", "Pragmatic", "Assertive regional player"],
    "tamim": ["Low-key", "Mediator", "Consensus-seeking", "Independent"],
    "abdullah-ii": ["Moderate", "Diplomatic", "Cautious reformer", "Western-oriented"],
    "erdogan": ["Combative", "Populist", "Pragmatic", "Strong personal control"],
    "netanyahu": ["Security-first", "Hard-liner on statehood", "Skilled communicator", "Political survivor"],
    "pezeshkian": ["Conciliatory", "Plain-spoken", "Reformist within the system", "Consensus-seeking"],
    "abbas": ["Cautious", "Legalistic", "Diplomacy over force", "Long-serving"],
    "sharaa": ["Pragmatic", "Transitional leader", "Unity-focused", "Courts foreign support"],
    "madbouly": ["Technocratic", "Detail-focused", "Delivery-oriented", "Public explainer"],
    "abdelatty": ["Energetic", "Hands-on diplomat", "Mediator", "Crisis manager"],
    "hassan-abdalla": ["Technical", "Low-profile", "Inflation-focused", "Data-driven"],
    "el-tayeb": ["Scholarly", "Moderate", "Independent-minded", "Interfaith bridge-builder"],
    "tawadros": ["Pastoral", "Conciliatory", "Unity-focused", "Non-partisan"],
    "sawiris": ["Outspoken", "Liberal", "Pro-market", "Blunt"],
}

# How headlines name each person, English then Arabic. The first of each is searched.
ALIASES = {
    "sisi": (["Sisi"], ["السيسي"]),
    "mbs": (["bin Salman", "Saudi crown prince", "Crown Prince Mohammed", "MBS"],
            ["محمد بن سلمان", "ولي العهد السعودي", "ولي العهد"]),
    "mbz": (["bin Zayed", "UAE President", "UAE's president", "MBZ"], ["محمد بن زايد", "رئيس الدولة"]),
    "tamim": (["Tamim", "Emir of Qatar", "Qatar's emir", "Qatari emir"],
              ["تميم بن حمد", "أمير قطر", "أمير البلاد", "تميم"]),
    "abdullah-ii": (["King Abdullah", "Jordan's king", "Jordanian king"],
                    ["الملك عبدالله", "الملك عبد الله", "العاهل الأردني", "جلالة الملك"]),
    "erdogan": (["Erdogan", "Erdoğan"], ["أردوغان"]),
    "netanyahu": (["Netanyahu"], ["نتنياهو"]),
    "pezeshkian": (["Pezeshkian", "Iran's president", "Iranian president"], ["بزشكيان", "الرئيس الإيراني"]),
    "abbas": (["Abbas"], ["محمود عباس", "الرئيس الفلسطيني", "أبو مازن", "عباس"]),
    "sharaa": (["Sharaa", "Syria's president", "Syrian president"], ["الشرع", "الرئيس السوري"]),
    "madbouly": (["Madbouly"], ["مدبولي"]),
    "abdelatty": (["Abdelatty", "Abdel Aty", "Abdel-Aty"], ["عبد العاطي"]),
    "hassan-abdalla": (["Hassan Abdalla", "Hassan Abdullah"], ["حسن عبد الله", "حسن عبدالله"]),
    "el-tayeb": (["Tayeb", "Tayyeb", "Grand Imam"], ["شيخ الأزهر", "الإمام الأكبر", "الطيب"]),
    "tawadros": (["Tawadros"], ["البابا تواضروس", "تواضروس"]),
    "sawiris": (["Sawiris"], ["نجيب ساويرس", "ساويرس"]),
}

# key: (English name, Arabic name, English forms, Arabic forms). Forms find the
# country in a headline; the names are searched.
COUNTRIES = {
    "SA": ("Saudi Arabia", "السعودية", ["Saudi"], ["السعودية", "السعودي", "الرياض"]),
    "AE": ("United Arab Emirates", "الإمارات", ["UAE", "Emirati", "United Arab Emirates", "Abu Dhabi"],
           ["الإمارات", "الإماراتي", "أبوظبي"]),
    "US": ("United States", "الولايات المتحدة", ["United States", "U.S.", "US", "America", "American", "Washington"],
           ["الولايات المتحدة", "أمريكا", "الأمريكي", "الأمريكية", "واشنطن"]),
    "EU": ("European Union", "الاتحاد الأوروبي", ["European Union", "EU", "Europe", "European"],
           ["الاتحاد الأوروبي", "أوروبا", "الأوروبي", "الأوروبية"]),
    "CN": ("China", "الصين", ["China", "Chinese", "Beijing"], ["الصين", "الصيني", "الصينية", "بكين"]),
    "RU": ("Russia", "روسيا", ["Russia", "Russian", "Moscow"], ["روسيا", "الروسي", "الروسية", "موسكو"]),
    "JO": ("Jordan", "الأردن", ["Jordan", "Jordanian"], ["الأردن", "الأردني", "الأردنية"]),
    "ET": ("Ethiopia", "إثيوبيا", ["Ethiopia", "Ethiopian", "GERD"], ["إثيوبيا", "الإثيوبي", "الإثيوبية", "سد النهضة"]),
    "SD": ("Sudan", "السودان", ["Sudan", "Sudanese"], ["السودان", "السوداني", "السودانية"]),
    "LY": ("Libya", "ليبيا", ["Libya", "Libyan"], ["ليبيا", "الليبي", "الليبية"]),
    "IL": ("Israel", "إسرائيل", ["Israel", "Israeli"], ["إسرائيل", "الإسرائيلي", "الإسرائيلية", "الاحتلال"]),
    "EG": ("Egypt", "مصر", ["Egypt", "Egyptian", "Cairo"], ["مصر", "المصري", "المصرية", "القاهرة"]),
    "PK": ("Pakistan", "باكستان", ["Pakistan", "Pakistani"], ["باكستان", "الباكستاني"]),
    "IR": ("Iran", "إيران", ["Iran", "Iranian", "Tehran"], ["إيران", "الإيراني", "الإيرانية", "طهران"]),
    "YE": ("Yemen", "اليمن", ["Yemen", "Yemeni", "Houthi", "Houthis"], ["اليمن", "اليمني", "الحوثي", "الحوثيين"]),
    "FR": ("France", "فرنسا", ["France", "French"], ["فرنسا", "الفرنسي", "الفرنسية"]),
    "IN": ("India", "الهند", ["India", "Indian"], ["الهند", "الهندي", "الهندية"]),
    "TR": ("Turkey", "تركيا", ["Turkey", "Türkiye", "Turkish", "Ankara"], ["تركيا", "التركي", "التركية", "أنقرة"]),
    "KW": ("Kuwait", "الكويت", ["Kuwait", "Kuwaiti"], ["الكويت", "الكويتي"]),
    "OM": ("Oman", "سلطنة عمان", ["Oman", "Omani"], ["سلطنة عمان", "العماني", "العمانية"]),
    "GB": ("United Kingdom", "بريطانيا", ["United Kingdom", "Britain", "British", "UK"],
           ["بريطانيا", "البريطاني", "البريطانية", "المملكة المتحدة"]),
    "IQ": ("Iraq", "العراق", ["Iraq", "Iraqi", "Baghdad"], ["العراق", "العراقي", "العراقية", "بغداد"]),
    "SY": ("Syria", "سوريا", ["Syria", "Syrian", "Damascus"], ["سوريا", "سورية", "السوري", "السورية", "دمشق"]),
    "QA": ("Qatar", "قطر", ["Qatar", "Qatari", "Doha"], ["قطر", "القطري", "القطرية", "الدوحة"]),
    "AZ": ("Azerbaijan", "أذربيجان", ["Azerbaijan", "Azerbaijani", "Baku"], ["أذربيجان", "الأذربيجاني"]),
    "GR": ("Greece", "اليونان", ["Greece", "Greek", "Athens"], ["اليونان", "اليوناني", "اليونانية"]),
    "CY": ("Cyprus", "قبرص", ["Cyprus", "Cypriot"], ["قبرص", "القبرصي"]),
    "BH": ("Bahrain", "البحرين", ["Bahrain", "Bahraini"], ["البحرين", "البحريني"]),
    "MA": ("Morocco", "المغرب", ["Morocco", "Moroccan", "Rabat"], ["المغرب", "المغربي", "المغربية"]),
    "DE": ("Germany", "ألمانيا", ["Germany", "German", "Berlin"], ["ألمانيا", "الألماني", "الألمانية", "برلين"]),
    "PS": ("Palestine", "فلسطين", ["Palestine", "Palestinian", "Gaza", "West Bank"],
           ["فلسطين", "الفلسطيني", "الفلسطينية", "غزة", "الضفة"]),
}


def _form_re(forms: list[str]) -> re.Pattern:
    # Short capitals (US, UK, EU) must match exactly; other forms case-insensitively.
    parts = [rf"(?<![\w]){re.escape(f)}(?![\w])" if f.isupper() and len(f) <= 4
             else rf"(?i:(?<![\w]){re.escape(f)})" for f in forms]
    return re.compile("|".join(parts))


def _ar_norm(text: str) -> str:
    from .arabic import normalize
    return normalize(text)


_EN_FORMS = {k: _form_re(v[2]) for k, v in COUNTRIES.items()}
_AR_FORMS = {k: [_ar_norm(f) for f in v[3]] for k, v in COUNTRIES.items()}


def country_of(label: str) -> str | None:
    """The country an entry such as "Ethiopia (the Nile dam, GERD)" is about: the
    first one named in it, or None for groups and institutions."""
    found = [(m.start(), k) for k, rx in _EN_FORMS.items() if (m := rx.search(label))]
    return min(found)[1] if found else None


def in_arabic(sid: str, prof: dict | None) -> dict | None:
    """The compiled profile with its text in Arabic (built-in people only). Partners and
    rivals keep their country tags: the Arabic lists are in the same order."""
    from .stakeholders_ar import AR
    ar = AR.get(sid)
    if not prof or not ar:
        return prof
    out = {**prof, **{k: ar[k] for k in ("country", "background", "leadership_style", "memberships") if k in ar},
           "personality_type": ar.get("personality_type", prof.get("personality_type", []))}
    for k in ("partners", "frictions"):
        if len(ar.get(k, [])) == len(prof.get(k, [])):
            out[k] = [{**rel, "label": label} for rel, label in zip(prof[k], ar[k])]
    return out


def with_edits(sid: str, prof: dict | None, edit: dict) -> dict | None:
    """The profile with the hand-made changes laid over it (a person without a compiled
    profile gets one from the edit alone)."""
    if not edit:
        return prof
    base = prof or {"country": "", "cc": "", "name_local": "", "query_local": "", "official": [],
                    "background": "", "leadership_style": "", "memberships": [], "partners": [],
                    "frictions": [], "personality_type": []}
    out = {**base, **{k: v for k, v in edit.items() if k not in ("partners", "frictions")}}
    tag = lambda labels: [{"label": l, "country": (c := country_of(l)),
                           "country_name": COUNTRIES[c][0] if c else None,
                           "country_name_ar": COUNTRIES[c][1] if c else None}
                          for l in labels]
    for k in ("partners", "frictions"):
        if k in edit:
            out[k] = tag(edit[k])
    return out


def _with_details(sid: str, prof: dict) -> dict:
    """The profile with personality type, and each partner or rival tagged with its country."""
    tag = lambda labels: [{"label": l, "country": (c := country_of(l)),
                           "country_name": COUNTRIES[c][0] if c else None,
                           "country_name_ar": COUNTRIES[c][1] if c else None}
                          for l in labels]
    return {**prof, "personality_type": PERSONALITY.get(sid, []),
            "partners": tag(prof["partners"]), "frictions": tag(prof["frictions"])}


# --------------------------------------------------------------------------- #
# What the person said about a country
# --------------------------------------------------------------------------- #
# Words that make the person the speaker: "Erdogan says", "Sisi warns", "السيسي يؤكد".
_EN_SPEAKS = re.compile(
    r"^\W*(says|said|tells|told|slams|blasts|warns|accuses|praises|hails|urges|calls|vows|"
    r"condemns|stresses|affirms|insists|denies|rejects|thanks|welcomes|criticises|criticizes|"
    r"lashes|pledges|declares|announces|demands|threatens|reaffirms|lauds|commends|rebukes|"
    r"attacks|defends|blames|signals|appeals)\b|^'s\s+(speech|address|remarks|message|comments)\b",
    re.IGNORECASE)
_EN_SPEECH_BEFORE = re.compile(r"(speech|address|remarks) by\s*$", re.IGNORECASE)
# Headlines are matched after Arabic normalization (أ -> ا, ة -> ه), so the words are too.
_AR_VERBS = ("يؤكد أكد يقول قال يدعو دعا يحذر حذر يشيد أشاد يرحب رحب يدين أدان يطالب طالب يشدد "
             "شدد يتهم اتهم ينتقد انتقد يرفض رفض يثمن ثمن يهاجم هاجم يعلن أعلن يوجه وجه يكشف كشف "
             "يجدد جدد يعرب أعرب يندد ندد يشكر شكر يهنئ هنأ يبحث بحث يتلقى تلقى يستقبل استقبل يلقي ألقى")
_AR_SPEAKS = None  # built below, once _ar_norm exists
_AR_SPEECH_WORDS = "كلمة كلمته خطاب خطابه تصريحات تصريح"
_AR_SPEECH_BEFORE = None

# The report's wording decides the tone. Each cue is a word stem.
_TONE = {
    "positive": {
        "en": ["praise", "hail", "thank", "welcom", "commend", "laud", "partner", "cooperat",
               "friend", "brother", "strengthen", "boost", "deepen", "agree", "alliance", "ally",
               "solidarity", "congratulat", "support", "invest", "ties with", "appreciat", "value"],
        "ar": ["يشيد", "أشاد", "يثمن", "ثمن", "يرحب", "رحب", "يشكر", "شكر", "تعاون", "شراك",
               "أخوي", "الأشقاء", "الشقيق", "تعزيز", "دعم", "يهنئ", "هنأ", "صداق", "تضامن", "اتفاق",
               "استثمار", "تقدير", "يعرب عن تقدير"],
    },
    "negative": {
        "en": ["accus", "slam", "condemn", "critici", "blast", "warn", "threat", "attack",
               "denounc", "reject", "blame", "aggression", "occupation", "genocid", "war ",
               "strike", "sanction", "hostil", "enemy", "terror", "destabili", "violat", "tyrant",
               "rebuk", "lash", "red line", "must not", "against", "topple", "overthrow",
               "destroy", "eliminat", "defeat", "regime", "danger", "menace", "punish", "retaliat",
               "fail", "useless", "corrupt", "waste", "disgrace", "ripoff", "rip off", "unfair",
               "taken advantage", "abuse"],
        "ar": ["يدين", "أدان", "ينتقد", "انتقد", "يحذر", "حذر", "يتهم", "اتهم", "يرفض", "رفض",
               "عدوان", "الاحتلال", "إبادة", "حرب", "تهديد", "هجوم", "العدو", "إرهاب", "انتهاك",
               "يندد", "ندد", "جرائم", "يهاجم", "هاجم", "سنسقط", "إسقاط", "نسقط", "تدمير", "القضاء على",
               "خطر", "النظام الإيراني", "عقوبات", "الانتقام", "فشل", "فشلت", "عجز", "تقاعس"],
    },
}
_AR_SPEAKS = re.compile(r"^\s*(:|" + "|".join(map(re.escape, _ar_norm(_AR_VERBS).split())) + r")(?!\w)")
_AR_SPEECH_BEFORE = re.compile(r"(" + "|".join(map(re.escape, _ar_norm(_AR_SPEECH_WORDS).split()))
                               + r")\s+(" + "|".join(map(re.escape, _ar_norm("الرئيس الملك الأمير").split()))
                               + r")?\s*$")
_TONE_NORM = {pole: {"en": cues["en"], "ar": [_ar_norm(c) for c in cues["ar"]]}
              for pole, cues in _TONE.items()}

# A cue right after one of these doesn't count: "did not threaten", "lifting sanctions",
# "an end to the war", "لم نهدد", "رفع العقوبات", "إنهاء الحرب".
_NEGATION = re.compile(
    r"(\b(not|no|never|didn't|did not|won't|doesn't|denies|lift|lifts|lifted|lifting|ease|eases|"
    r"easing|eased|end|ends|ended|ending|without)\b"
    r"|(^|\s)[وبل]?(لم|لا|لن|ليس|ما|غير|مش|رفع|إنهاء|انهاء|وقف|بدون|دون)\s)[^.;:,،]*$")

# Where it was said, when the report names it. Venues anywhere in the headline;
# cities only after "in"/"at"/"في", since "Jerusalem hits back" names a government.
_PLACES = [
    (r"UN General Assembly|UNGA|General Assembly|الجمعية العامة", "UN General Assembly, New York"),
    (r"Security Council|مجلس الأمن", "UN Security Council"),
    (r"\bUN\b|U\.N\.|United Nations|الأمم المتحدة", "United Nations"),
    (r"Arab League|Arab summit|الجامعة العربية|القمة العربية", "Arab League summit"),
    (r"Arab-Islamic summit|القمة العربية الإسلامية", "Arab-Islamic summit"),
    (r"\bGCC\b|Gulf summit|القمة الخليجية|مجلس التعاون", "GCC summit"),
    (r"BRICS|بريكس", "BRICS summit"), (r"\bG20\b|مجموعة العشرين", "G20 summit"),
    (r"\bCOP\s?\d+|مؤتمر المناخ", "UN climate conference (COP)"),
    (r"Davos|World Economic Forum|دافوس", "World Economic Forum, Davos"),
    (r"Munich Security|ميونخ", "Munich Security Conference"),
    (r"Shura Council|مجلس الشورى", "Shura Council"), (r"Knesset|الكنيست", "Knesset"),
    (r"parliament|البرلمان|مجلس النواب|مجلس الأمة|TBMM", "Parliament"),
    (r"Throne speech|خطاب العرش", "Throne speech, parliament"),
    (r"press conference|مؤتمر صحفي", "Press conference"),
    (r"interview|مقابلة|حوار", "Interview"),
    (r"Sharm el-Sheikh|شرم الشيخ", "Sharm el-Sheikh"),
]
_CITIES = [
    (r"New York|نيويورك", "New York"),
    (r"Cairo|القاهرة", "Cairo"), (r"Riyadh|الرياض", "Riyadh"), (r"Jeddah|جدة", "Jeddah"),
    (r"Abu Dhabi|أبوظبي", "Abu Dhabi"), (r"Doha|الدوحة", "Doha"), (r"Amman\b", "Amman"),
    (r"Ankara|أنقرة", "Ankara"), (r"Istanbul|إسطنبول", "Istanbul"), (r"Tehran|طهران", "Tehran"),
    (r"Jerusalem|القدس", "Jerusalem"), (r"Damascus|دمشق", "Damascus"), (r"Baghdad|بغداد", "Baghdad"),
    (r"Washington|واشنطن", "Washington"), (r"Paris|باريس", "Paris"), (r"London|لندن", "London"),
    (r"Moscow|موسكو", "Moscow"), (r"Beijing|بكين", "Beijing"), (r"Brussels|بروكسل", "Brussels"),
    (r"Baku|باكو", "Baku"),
]
_PLACES = ([(re.compile(p, re.IGNORECASE), name) for p, name in _PLACES]
           + [(re.compile(rf"(\b(in|at|from)\s+|(في|من)\s+|(?<!\w)ب)({p})", re.IGNORECASE), name)
              for p, name in _CITIES])


def _speaker_is(title: str, en_forms: list[str], ar_forms: list[str]) -> bool:
    """True when the headline reports the person speaking, not someone speaking about them."""
    for form in en_forms:
        for m in re.finditer(rf"(?<!\w){re.escape(form)}(?!\w)", title, re.IGNORECASE):
            after, before = title[m.end():], title[:m.start()]
            if _EN_SPEAKS.search(after) or _EN_SPEECH_BEFORE.search(before):
                return True
    norm = _ar_norm(title)
    for form in ar_forms:
        f = _ar_norm(form)
        start = 0
        while (i := norm.find(f, start)) >= 0:
            if _AR_SPEAKS.search(norm[i + len(f):]) or _AR_SPEECH_BEFORE.search(norm[:i]):
                return True
            start = i + 1
    return False


def _mentions_country(title: str, key: str) -> bool:
    return bool(_EN_FORMS[key].search(title)) or any(f in _ar_norm(title) for f in _AR_FORMS[key])


def tone_of(title: str) -> tuple[str, list[str]]:
    """'positive', 'negative', 'mixed' or 'neutral', and the words that decided it."""
    low, norm = f" {title.lower()} ", _ar_norm(title)

    def said(cue: str, text: str) -> bool:
        # "we did not threaten", "لم نوجه تهديدا": a negated cue doesn't count.
        for m in re.finditer(re.escape(cue), text):
            if not _NEGATION.search(text[max(0, m.start() - 18):m.start()]):
                return True
        return False

    found = {pole: [c for c in cues["en"] if said(c, low)] + [c for c in cues["ar"] if said(c, norm)]
             for pole, cues in _TONE_NORM.items()}
    # "يهاجم" also contains "هاجم": list each word once.
    found = {p: [c for c in cs if not any(c != o and c in o for o in cs)] for p, cs in found.items()}
    pos, neg = found["positive"], found["negative"]
    tone = "mixed" if pos and neg else "positive" if pos else "negative" if neg else "neutral"
    return tone, [c.strip() for c in pos + neg]


def place_of(title: str) -> str | None:
    for rx, name in _PLACES:
        if rx.search(title):
            return name
    return None


def mentions(sid: str, key: str) -> dict:
    """What `sid` said about country `key` over the past year, from trusted reports.

    A report is kept when it comes from a trusted outlet, names the country, and its
    headline shows the person speaking ("Erdogan says...", "السيسي: ..."), not someone
    else speaking about them. Each gets the report's date, the place if the report
    names it, and a tone read from the headline's wording by fixed word lists (no AI).
    """
    cache_key = f"m:{sid}:{key}"
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    en_forms, ar_forms = ALIASES[sid]
    en_name, ar_name = COUNTRIES[key][0], COUNTRIES[key][1]
    jobs = {
        "en": lambda: _news(f"{en_forms[0]} {en_name}", "en", "US", 365),
        "en_speech": lambda: _news(f"{en_forms[0]} {en_name} (speech OR address OR says)", "en", "US", 365),
        "ar": lambda: _news(f"{ar_forms[0]} {ar_name}", "ar", "EG", 365),
    }
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        for k, fut in {k: pool.submit(f) for k, f in jobs.items()}.items():
            try:
                items += fut.result()
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                errors.append(f"{k}: {type(exc).__name__}")
    kept, seen = [], set()
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        title = it["title"]
        dedupe = re.sub(r"\W+", "", title.lower())[:80]
        if dedupe in seen or outlet_country(it["domain"]) is None:
            continue
        if not _mentions_country(title, key) or not _speaker_is(title, en_forms, ar_forms):
            continue
        seen.add(dedupe)
        tone, cues = tone_of(title)
        kept.append({**it, "tone": tone, "cues": cues, "place": place_of(title)})
    counts = {t: sum(1 for k in kept if k["tone"] == t) for t in ("positive", "negative", "mixed", "neutral")}
    out = {"country": key, "country_name": en_name, "country_name_ar": ar_name,
           "items": kept[:20], "total": len(kept), "counts": counts, "errors": errors}
    if not errors:
        _cache[cache_key] = (time.time(), out)
    return out
