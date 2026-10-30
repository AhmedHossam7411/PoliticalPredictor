"""Integrated scoring: LTA traits + VICS indices, with norming and validation.

`analyze(text)` returns a JSON-friendly dict combining both methodologies.
LTA High/Moderate/Low labels are assigned *relative to a norming corpus*
(Hermann's rule: >1 SD above the mean = High, <1 SD below = Low), defaulting
to the mock speeches -- the English ones for English text, their Arabic
(Modern Standard + Egyptian) renderings for Arabic text. VICS word lists are
English-only, so VICS is skipped for Arabic input.
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


def analyze_with_bands(text: str, norm: dict | None = None) -> dict:
    """analyze() plus a High/Moderate/Low label per LTA trait."""
    result = analyze(text)
    if norm is None:
        norm = default_norm(result["input"]["language"])
    for t in LTA_TRAITS:
        tr = result["lta"]["traits"][t]
        tr["band"] = band(tr["value"], norm[t]["mean"], norm[t]["std"])
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
        lines.append(f"  {t:5} {tr['value']:7.3f}{unit:4}  {tr['band']}")
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
