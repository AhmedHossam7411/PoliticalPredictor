"""Integrated scoring: LTA traits + VICS indices, with norming and validation.

`analyze(text)` returns a JSON-friendly dict combining both methodologies.
LTA High/Moderate/Low labels are assigned *relative to a norming corpus*
(Hermann's rule: >1 SD above the mean = High, <1 SD below = Low), defaulting
to the five mock speeches.
"""
from __future__ import annotations

import statistics
from typing import Iterable

from .lta import score_lta, TRAITS as LTA_TRAITS
from .vics import score_vics
from .mock_speeches import MOCK_SPEECHES

LABEL_RANK = {"Low": 0, "Moderate": 1, "High": 2}


def analyze(text: str) -> dict:
    """Score one text on both methodologies (raw, un-normed)."""
    return {"lta": score_lta(text), "vics": score_vics(text)}


# --------------------------------------------------------------------------- #
# Norming: turn raw LTA values into High/Moderate/Low vs a comparison group
# --------------------------------------------------------------------------- #
def build_norm(corpus_texts: Iterable[str]) -> dict[str, dict[str, float]]:
    """Mean and population SD of each LTA trait value across a corpus."""
    per_trait: dict[str, list[float]] = {t: [] for t in LTA_TRAITS}
    for text in corpus_texts:
        traits = score_lta(text)["traits"]
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
    if norm is None:
        norm = default_norm()
    result = analyze(text)
    for t in LTA_TRAITS:
        tr = result["lta"]["traits"][t]
        tr["band"] = band(tr["value"], norm[t]["mean"], norm[t]["std"])
    return result


_DEFAULT_NORM: dict | None = None


def default_norm() -> dict:
    global _DEFAULT_NORM
    if _DEFAULT_NORM is None:
        _DEFAULT_NORM = build_norm(s["text"] for s in MOCK_SPEECHES.values())
    return _DEFAULT_NORM


# --------------------------------------------------------------------------- #
# Validation: does the scorer order speeches the way their labels imply?
# --------------------------------------------------------------------------- #
def validate_mock() -> dict:
    """Pairwise concordance between stated labels and computed values.

    For each trait, over every pair of mock speeches with *different* stated
    labels, check the computed values order them the same way. Returns the
    concordance fraction per trait and overall.
    """
    scored = {
        name: score_lta(s["text"])["traits"]
        for name, s in MOCK_SPEECHES.items()
    }
    names = list(MOCK_SPEECHES)
    per_trait = {}
    tot_conc = tot_pairs = 0
    for t in LTA_TRAITS:
        conc = pairs = 0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                la = LABEL_RANK[MOCK_SPEECHES[a]["profile"][t]]
                lb = LABEL_RANK[MOCK_SPEECHES[b]["profile"][t]]
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
        print("=== Validation against mock-speech profiles ===\n")
        v = validate_mock()
        for t, d in v["per_trait"].items():
            rate = "n/a" if d["rate"] is None else f"{d['rate']*100:5.1f}%"
            print(f"  {t:5} {rate}  ({d['concordant']}/{d['pairs']} ordered pairs)")
        overall = v["overall_rate"]
        print(f"\n  overall ordering concordance: {overall*100:.1f}%")
        print("\n=== Example report: P1 Expansionist Crusader ===\n")
        print(format_report(MOCK_SPEECHES["P1_Expansionist_Crusader"]["text"]))
