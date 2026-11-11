"""Leadership Trait Analysis (Hermann) -- lemma + POS dictionary scoring.

Seven traits: BACE, PWR, CC, SC, TASK, DIS, IGB.

Matching is lemma-based (so "possibilities" matches "possibility") with
optional part-of-speech filters that follow Hermann's coding intent:
    BACE, PWR -> verbs only (agency / influence as action)
    TASK      -> nouns only  (work/goal nouns; this also splits the heavy
                              BACE/TASK list overlap: "to plan" vs "a plan")
    DIS       -> nouns + adjectives (threats and suspicious descriptors)
    CC, SC, IGB -> any POS (markers span several classes)

CC, SC and TASK set two lists against each other: the value is the first list's
share of the hits (60% high + 40% low CC = high CC; TASK: problem-solving vs
relationship). BACE, PWR, DIS and IGB are one list each, as a density (per 1000
tokens), with High/Moderate/Low assigned later relative to a norming group.

BACE and PWR count only actions by the speaker or their group: a word is left out
when the grammar shows someone else acts ("they built") or the action is denied
("we cannot control"); see predictor.actor. The left-out words are reported as
"skipped" so the UI can show them.

Arabic text (Modern Standard or Egyptian) is scored the same way against the
Arabic lexicons, with clitic-aware matching from predictor.arabic instead of
spaCy (no POS filters). Arabic densities are not comparable with English ones,
so Arabic texts must be normed against an Arabic corpus.
"""
from __future__ import annotations

from . import arabic
from .dictionaries import lta_dictionaries, lta_dictionaries_ar
from .nlp import count_agency, count_lemma, content_token_count

TRAITS = ("BACE", "PWR", "CC", "SC", "TASK", "DIS", "IGB")
RATIO_TRAITS = ("CC", "SC", "TASK")
DENSITY_TRAITS = ("BACE", "PWR", "DIS", "IGB")

# Per-trait POS filter for single-word lemma matches (None = any POS).
# POS filtering is Hermann-faithful but, on the available synthetic data, it
# reduces recall more than it helps (power/distrust words appear as nouns too),
# so it is OFF by default and gated behind USE_POS until we have grammatically
# realistic, expert-coded validation speeches.
USE_POS = False
_POS = {
    "BACE": frozenset({"VERB"}),
    "PWR": frozenset({"VERB"}),
    "TASK": frozenset({"NOUN", "PROPN"}),
    "DIS": frozenset({"NOUN", "PROPN", "ADJ"}),
}


def _fs(words) -> frozenset:
    return frozenset(words)


def _pos_for(trait: str) -> frozenset | None:
    return _POS.get(trait) if USE_POS else None


AGENCY_TRAITS = ("BACE", "PWR")


def _counters(language: str):
    """(dictionaries, term counter, agency counter, token counter) for a language."""
    if language == "ar":
        return (lta_dictionaries_ar(),
                lambda text, words, _pos=None: arabic.count_terms(text, words),
                lambda text, words, _pos=None: arabic.count_terms_agency(text, words),
                arabic.token_count)
    return lta_dictionaries(), count_lemma, count_agency, content_token_count


def score_lta(text: str, language: str | None = None) -> dict:
    """Return raw LTA metrics for one text (English: lemma + POS; Arabic: clitic-aware).

    `language` is "en" or "ar"; detected from the script when omitted.
    """
    language = language or ("ar" if arabic.is_arabic(text) else "en")
    d, count_lemma, count_agency, content_token_count = _counters(language)
    tokens = content_token_count(text) or 1
    out: dict = {"tokens": tokens, "language": language, "traits": {}}

    def density(count: int) -> float:
        return 1000.0 * count / tokens

    # --- Conceptual complexity, self-confidence: high vs low lists (ratio, any POS).
    for trait in ("CC", "SC"):
        high_n, high_hits = count_lemma(text, _fs(d[f"{trait}_high"]))
        low_n, low_hits = count_lemma(text, _fs(d[f"{trait}_low"]))
        total = high_n + low_n
        out["traits"][trait] = {
            "kind": "ratio", "high": high_n, "low": low_n,
            "value": (high_n / total) if total else 0.5,
            "matches": {"high": high_hits, "low": low_hits},
        }

    # --- Task focus: problem-solving vs relationship words (ratio).
    task_n, task_hits = count_lemma(text, _fs(d["TASK"]), _pos_for("TASK"))
    grp_n, grp_hits = count_lemma(text, _fs(d["TASK_group"]))
    task_total = task_n + grp_n
    out["traits"]["TASK"] = {
        "kind": "ratio", "task": task_n, "group": grp_n,
        "value": (task_n / task_total) if task_total else 0.5,
        "matches": {"task": task_hits, "group": grp_hits},
    }

    # --- Density traits (verbs for BACE/PWR, noun/adj for DIS, any IGB).
    for trait in ("BACE", "PWR", "DIS", "IGB"):
        if trait in AGENCY_TRAITS:
            n, hits, skipped = count_agency(text, _fs(d[trait]), _pos_for(trait))
        else:
            (n, hits), skipped = count_lemma(text, _fs(d[trait]), _pos_for(trait)), None
        out["traits"][trait] = {"kind": "density", "count": n,
                                "value": density(n), "matches": hits}
        if skipped is not None:
            # Words on the list that weren't counted, and why.
            out["traits"][trait]["skipped"] = {r: sum(m.values()) for r, m in skipped.items()}
            out["traits"][trait]["skipped_matches"] = skipped

    return out


if __name__ == "__main__":
    sample = (
        "We will defend our people. However, the situation is complex and "
        "depends on many factors. I believe I can shape these events. Perhaps "
        "we must achieve our objective and implement our plans together."
    )
    result = score_lta(sample)
    print(f"tokens={result['tokens']}")
    for t in TRAITS:
        tr = result["traits"][t]
        print(f"  {t:5} value={tr['value']:.3f}  ({tr['kind']})")
