"""Arabic text support for the dictionary scorer.

spaCy's English pipeline can't lemmatize Arabic, and Arabic glues clitics onto
words ("وسنحقق" = and + will + we + achieve; "بلدنا" = country + our), so plain
word matching would miss almost everything. This module provides:

  * detect(text)        -- English vs Arabic, and for Arabic a Modern Standard
                           vs Egyptian colloquial estimate from marker words;
  * normalize(text)     -- strip diacritics/tatweel, unify alef/ya/ta-marbuta
                           and hamza seats (ء ؤ ئ -> ء), so spelling variants
                           compare equal (Egyptian ي-for-hamza spellings such
                           as خاين / نتايج are listed separately in the lexicons);
  * count_terms(...)    -- lexicon hits where each token may match after peeling
                           common prefixes (و ف ب ل ك س ال، Egyptian ح/ه future,
                           imperfect ي ت ن ا) and suffixes (pronoun clitics,
                           plural/dual endings, Egyptian negation ش);
  * count_pronouns(...) -- closed-class first-person words (for SC).

Entries of two letters or fewer (e.g. "لو", "شك") only match after peeling
the conjunction and article, not the full clitic set, to avoid false hits
such as "فقد" (lost) -> "قد".
"""
from __future__ import annotations

import re
from functools import lru_cache

_AR_LETTER = re.compile(r"[ؠ-يٮ-ۓۺ-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TOKEN = re.compile(r"[ء-ي]+")

_CHAR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    # Hamza seats collapse to ء so أعداء / أعدائنا / أعداؤنا share a stem.
    "ى": "ي", "ئ": "ء", "ؤ": "ء", "ة": "ه",
    "ک": "ك", "ی": "ي", "ـ": "",
})


def is_arabic(text: str) -> bool:
    """True when Arabic letters outnumber Latin ones."""
    ar = len(_AR_LETTER.findall(text))
    return ar > 0 and ar >= len(_LATIN_LETTER.findall(text))


def normalize(text: str) -> str:
    return _DIACRITICS.sub("", text).translate(_CHAR_MAP)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def token_count(text: str) -> int:
    return len(tokens(text))


# --------------------------------------------------------------------------- #
# Clitic peeling
# --------------------------------------------------------------------------- #
_CONJ = ("و", "ف")
_ARTICLE = ("بال", "كال", "لل", "ال")
_PREP = ("ب", "ك", "ل", "س")
_EG_FUTURE = ("ح", "ه")          # Egyptian future: هنعمل / حنعمل
_IMPERFECT = ("ي", "ت", "ن", "ا")
_SUFFIXES = ("هما", "كما", "تين", "ها", "هم", "هن", "كم", "كن", "نا", "ني",
             "ات", "ون", "ين", "ان", "وا", "تم", "يه", "ه", "ك", "ي", "ت", "ش")
_MIN_STEM = 2


def _peel_prefixes(word: str, stages) -> set[str]:
    out = {word}
    for stage in stages:
        out |= {v[len(p):] for v in out for p in stage
                if v.startswith(p) and len(v) - len(p) >= _MIN_STEM}
    return out


def _peel_suffixes(word: str, rounds: int = 2) -> set[str]:
    out = {word}
    for _ in range(rounds):
        out |= {v[:-len(s)] for v in out for s in _SUFFIXES
                if v.endswith(s) and len(v) - len(s) >= _MIN_STEM}
    return out


@lru_cache(maxsize=65536)
def variants(word: str) -> frozenset[str]:
    """Every form `word` could take once clitics are peeled (incl. itself)."""
    prefixed = _peel_prefixes(word, (_CONJ, _ARTICLE + _PREP, _EG_FUTURE, _IMPERFECT))
    return frozenset(s for p in prefixed for s in _peel_suffixes(p))


@lru_cache(maxsize=65536)
def light_variants(word: str) -> frozenset[str]:
    """Conjunction + article only -- for very short entries and pronouns."""
    return frozenset(_peel_prefixes(word, (_CONJ, _ARTICLE)))


def _matches(token: str, entry: str) -> bool:
    if len(entry) <= 2:
        return entry in light_variants(token)
    return entry in variants(token)


@lru_cache(maxsize=64)
def compile_lexicon(entries: frozenset[str]) -> tuple[dict, dict, tuple]:
    """Split a raw lexicon into short/long single-word maps and multi-word phrases.

    Maps go normalized form -> original entry, so reported matches stay readable.
    """
    short: dict[str, str] = {}
    long: dict[str, str] = {}
    multi: list[tuple[tuple[str, ...], str]] = []
    for entry in entries:
        words = tuple(tokens(entry))
        if len(words) == 1:
            (short if len(words[0]) <= 2 else long)[words[0]] = entry
        elif words:
            multi.append((words, entry))
    return short, long, tuple(multi)


def count_terms(text: str, entries: frozenset[str]) -> tuple[int, dict[str, int]]:
    """Count lexicon hits in Arabic text (one hit per token for single words)."""
    toks = tokens(text)
    short, long, multi = compile_lexicon(entries)
    hits: dict[str, int] = {}
    total = 0
    for tok in toks:
        hit = next((long[v] for v in sorted(variants(tok), key=len, reverse=True)
                    if v in long), None)
        if hit is None:
            hit = next((short[v] for v in light_variants(tok) if v in short), None)
        if hit is not None:
            hits[hit] = hits.get(hit, 0) + 1
            total += 1
    n = len(toks)
    for words, entry in multi:
        L = len(words)
        for i in range(n - L + 1):
            if all(_matches(toks[i + k], words[k]) for k in range(L)):
                hits[entry] = hits.get(entry, 0) + 1
                total += 1
    return total, hits


def count_pronouns(text: str, entries: frozenset[str]) -> tuple[int, dict[str, int]]:
    """Closed-class words: match after peeling only a leading و/ف.

    Not the article -- "اللي" (Egyptian "which") must not count as "لي" (me).
    """
    lookup = {tokens(e)[0]: e for e in entries if tokens(e)}
    hits: dict[str, int] = {}
    total = 0
    for tok in tokens(text):
        hit = next((lookup[v] for v in _peel_prefixes(tok, (_CONJ,)) if v in lookup), None)
        if hit is not None:
            hits[hit] = hits.get(hit, 0) + 1
            total += 1
    return total, hits


# --------------------------------------------------------------------------- #
# Language / dialect detection
# --------------------------------------------------------------------------- #
# Words that are near-diagnostic of Egyptian colloquial vs Modern Standard.
# Deliberately excludes words common to both (يعني، اللي is kept: rare in MSA).
_EGYPTIAN = frozenset(normalize(w) for w in """
مش مفيش مفيهاش مافيش عايز عايزه عايزين عاوز عاوزين دلوقتي دلوقت كده كدا ازاي
إزاي ليه فين امتى إمتى بتاع بتاعه بتاعت بتاعتنا بتاعنا بتوع اوي أوي خالص
احنا إحنا انتو انتوا ده دي اللي علشان عشان برضه برضو اهو أهو ايوه أيوه لسه
زي حاجه حاجة حاجات كتير شويه شوية النهارده النهاردة بكره بكرة امبارح ولادنا
عيال جدعان بيقول بنقول هنعمل حنعمل مينفعش ماينفعش محدش ماحدش لينا ليا معايا
""".split())
_MSA = frozenset(normalize(w) for w in """
سوف لن لم ليس ليست هذا هذه ذلك تلك الذي التي الذين اللذين اللتين لقد إنني
حيث إذ إذا كي لكي أيها أيتها أولئك هؤلاء ماذا لماذا كيف متى أين
الآن فحسب بيد ثمة لدى لدينا لديهم نحن أنتم
""".split())


def _marker_tokens(toks: list[str]) -> tuple[list[str], list[str]]:
    eg, msa = [], []
    for tok in toks:
        if light_variants(tok) & _EGYPTIAN:
            eg.append(tok)
        elif tok in _MSA or (tok[:1] in _CONJ and tok[1:] in _MSA):
            msa.append(tok)
        # Egyptian negation circumfix: مـ...ـش (مبنخافش، معملناش)
        elif tok.startswith("م") and tok.endswith("ش") and len(tok) >= 5:
            eg.append(tok)
    return eg, msa


def detect(text: str) -> dict:
    """Input language, and for Arabic an MSA / Egyptian / mixed estimate.

    The estimate is a marker-word ratio, so it is a hint for the reader and the
    LLM prompt, not a classifier to report as fact.
    """
    if not is_arabic(text):
        return {"language": "en", "dialect": None}
    toks = tokens(text)
    eg, msa = _marker_tokens(toks)
    n_eg, n_msa = len(eg), len(msa)
    share = n_eg / (n_eg + n_msa) if (n_eg + n_msa) else 0.0
    # Egyptian markers are denser per sentence than MSA ones, so "egyptian"
    # needs a clear majority; a half-and-half speech lands around 0.7.
    if n_eg + n_msa < 3 or share < 0.3:
        dialect = "msa"
    elif share >= 0.8:
        dialect = "egyptian"
    else:
        dialect = "mixed"
    return {
        "language": "ar", "dialect": dialect,
        "egyptian_markers": n_eg, "msa_markers": n_msa,
        "egyptian_share": round(share, 2),
        "examples": sorted(set(eg), key=eg.index)[:8],
    }


DIALECT_NAMES = {
    "msa": "Modern Standard Arabic (Fusha)",
    "egyptian": "Egyptian colloquial Arabic",
    "mixed": "a mix of Modern Standard and Egyptian colloquial Arabic",
}
