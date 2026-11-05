"""Integrated scoring: LTA traits + VICS indices, with norming and validation.

`analyze(text)` returns a JSON-friendly dict combining both methodologies.
BACE, PWR, DIS and IGB get High/Moderate/Low *relative to a norming corpus*
(Hermann's rule: >1 SD above the mean = High, <1 SD below = Low), defaulting
to the mock speeches -- the English ones for English text, their Arabic
(Modern Standard + Egyptian) renderings for Arabic text. CC, SC and TASK set two
lists against each other, so whichever has the larger share of the hits decides:
High or Low, and for TASK a category. VICS word lists are English-only, so VICS
is skipped for Arabic input.
"""
from __future__ import annotations

import statistics
from typing import Iterable

from . import arabic
from .lta import score_lta, TRAITS as LTA_TRAITS
from .vics import score_vics
from .mock_speeches import MOCK_SPEECHES
from .mock_speeches_ar import MOCK_SPEECHES_AR

LABEL_RANK = {"Low": 0, "Moderate": 1, "High": 2}


def analyze(text: str) -> dict:
    """Score one text on both methodologies (raw, un-normed).

    `input` reports the detected language (and Arabic dialect estimate).
    """
    detected = arabic.detect(text)
    lang = detected["language"]
    return {"input": detected,
            "lta": score_lta(text, lang),
            "vics": score_vics(text) if lang == "en" else {},
            "vics_supported": lang == "en"}


# --------------------------------------------------------------------------- #
# Norming: turn raw LTA values into High/Moderate/Low vs a comparison group
# --------------------------------------------------------------------------- #
def build_norm(corpus_texts: Iterable[str],
               language: str | None = None) -> dict[str, dict[str, float]]:
    """Mean and population SD of each LTA trait value across a corpus."""
    per_trait: dict[str, list[float]] = {t: [] for t in LTA_TRAITS}
    for text in corpus_texts:
        traits = score_lta(text, language)["traits"]
        for t in LTA_TRAITS:
            per_trait[t].append(traits[t]["value"])
    norm = {}
    for t, vals in per_trait.items():
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        norm[t] = {"mean": mean, "std": std}
    return norm


def band(value: float, mean: float, std: float) -> str:
    if std == 0:
        return "Moderate"
    if value > mean + std:
        return "High"
    if value < mean - std:
        return "Low"
    return "Moderate"


# (first list ahead, second list ahead, neither ahead or no hits)
_RATIO_OUTCOMES = {"CC": ("High", "Low", "Moderate"), "SC": ("High", "Low", "Moderate"),
                   "TASK": ("Problem-solving", "Relationship-building", "Balanced")}


def ratio_band(trait: str, share: float) -> str:
    """Outcome of a two-list trait from the first list's share of the hits."""
    first, second, tie = _RATIO_OUTCOMES[trait]
    return first if share > 0.5 else second if share < 0.5 else tie


# --------------------------------------------------------------------------- #
# Evidence weighting: short texts are weak evidence, so pull them toward average
# --------------------------------------------------------------------------- #
# A raw rate from 100 words (4 power words = 40/1k) is as extreme as one from
# 1000 words, but far less reliable. Each value is blended with the norm mean
# as if the text came with this much extra "average" material (a Bayesian
# posterior mean): long texts keep their own rate, short ones move toward 50%.
# Two-list traits blend toward an even split instead; that can't change which
# list is ahead, so thin evidence shows in their value and confidence, not band.
PRIOR_TOKENS = 300  # density traits: words of average text added
PRIOR_HITS = 10     # ratio traits (CC, TASK): marker words of average mix added


def weigh(tr: dict, tokens: int, mean: float) -> tuple[float, float]:
    """(evidence-weighted value, weight of the text's own evidence 0..1)."""
    if tr["kind"] == "ratio":
        hits, n = (tr["high"], tr["high"] + tr["low"]) if "high" in tr \
            else (tr["task"], tr["task"] + tr["group"])
        return (hits + PRIOR_HITS * 0.5) / (n + PRIOR_HITS), n / (n + PRIOR_HITS)
    return ((1000.0 * tr["count"] + PRIOR_TOKENS * mean) / (tokens + PRIOR_TOKENS),
            tokens / (tokens + PRIOR_TOKENS))


def confidence(weight: float) -> str:
    # Density: ~200 words -> medium, ~600 -> high. Ratio: ~7 hits -> medium, 20 -> high.
    return "high" if weight >= 2 / 3 else "medium" if weight >= 0.4 else "low"


def analyze_with_bands(text: str, norm: dict | None = None) -> dict:
    """analyze() plus an evidence-weighted value and High/Moderate/Low band per trait.

    `value` stays the raw rate (and `raw_band` its band); on density traits
    `band` uses the weighted value, so short texts need a strong, repeated signal
    to be extreme. `percent` is the figure to show: the list words' share of the
    text (density traits) or the first list's share of the hits (two-list traits).
    """
    result = analyze(text)
    if norm is None:
        norm = default_norm(result["input"]["language"])
    tokens = result["lta"]["tokens"]
    for t in LTA_TRAITS:
        tr = result["lta"]["traits"][t]
        mean, std = norm[t]["mean"], norm[t]["std"]
        tr["adjusted"], tr["weight"] = weigh(tr, tokens, mean)
        tr["confidence"] = confidence(tr["weight"])
        if tr["kind"] == "ratio":
            tr["percent"] = 100.0 * tr["value"]
            tr["raw_band"] = tr["band"] = ratio_band(t, tr["value"])
        else:
            tr["percent"] = tr["value"] / 10.0
            tr["raw_band"] = band(tr["value"], mean, std)
            tr["band"] = band(tr["adjusted"], mean, std)
    result["lta"]["weighting"] = {"prior_tokens": PRIOR_TOKENS, "prior_hits": PRIOR_HITS}
    return result


_DEFAULT_NORMS: dict[str, dict] = {}


def mock_corpus(language: str = "en") -> dict[str, dict]:
    return MOCK_SPEECHES_AR if language == "ar" else MOCK_SPEECHES


def default_norm(language: str = "en") -> dict:
    if language not in _DEFAULT_NORMS:
        _DEFAULT_NORMS[language] = build_norm(
            (s["text"] for s in mock_corpus(language).values()), language)
    return _DEFAULT_NORMS[language]


# --------------------------------------------------------------------------- #
# Validation: does the scorer order speeches the way their labels imply?
# --------------------------------------------------------------------------- #
def validate_mock(language: str = "en") -> dict:
    """Pairwise concordance between stated labels and computed values.

    For each trait, over every pair of mock speeches with *different* stated
    labels, check the computed values order them the same way. Returns the
    concordance fraction per trait and overall.
    """
    speeches = mock_corpus(language)
    scored = {
        name: score_lta(s["text"], language)["traits"]
        for name, s in speeches.items()
    }
    names = list(speeches)
    per_trait = {}
    tot_conc = tot_pairs = 0
    for t in LTA_TRAITS:
        conc = pairs = 0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                la = LABEL_RANK[speeches[a]["profile"][t]]
                lb = LABEL_RANK[speeches[b]["profile"][t]]
                if la == lb:
                    continue
                va = scored[a][t]["value"]
                vb = scored[b][t]["value"]
                pairs += 1
                if (la - lb) * (va - vb) > 0:
                    conc += 1
                elif (la - lb) * (va - vb) == 0 and va == vb:
                    pass  # tie in value, counts as non-concordant
        per_trait[t] = {"concordant": conc, "pairs": pairs,
                        "rate": conc / pairs if pairs else None}
        tot_conc += conc
        tot_pairs += pairs
    return {"per_trait": per_trait,
            "overall_rate": tot_conc / tot_pairs if tot_pairs else None}


# --------------------------------------------------------------------------- #
# Pretty reports
# --------------------------------------------------------------------------- #
def format_report(text: str, norm: dict | None = None) -> str:
    r = analyze_with_bands(text, norm)
    lines = ["LTA traits (band relative to norming corpus):"]
    for t in LTA_TRAITS:
        tr = r["lta"]["traits"][t]
        unit = "" if tr["kind"] == "ratio" else " /1k"
        lines.append(f"  {t:5} {tr['value']:7.3f}{unit:4} -> weighted {tr['adjusted']:7.3f}"
                     f"  {tr['band']:8} ({tr['confidence']} confidence)")
    lines.append("\nVICS operational code:")
    for code, res in r["vics"].items():
        if "value" in res:
            lines.append(f"  {code:8} {res['value']:7.3f}  {res['label']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            print(format_report(fh.read()))
    else:
        for lang in ("en", "ar"):
            print(f"=== Validation against mock-speech profiles ({lang}) ===\n")
            v = validate_mock(lang)
            for t, d in v["per_trait"].items():
                rate = "n/a" if d["rate"] is None else f"{d['rate']*100:5.1f}%"
                print(f"  {t:5} {rate}  ({d['concordant']}/{d['pairs']} ordered pairs)")
            overall = v["overall_rate"]
            print(f"\n  overall ordering concordance: {overall*100:.1f}%\n")
        print("\n=== Example report: P1 Expansionist Crusader ===\n")
        print(format_report(MOCK_SPEECHES["P1_Expansionist_Crusader"]["text"]))
