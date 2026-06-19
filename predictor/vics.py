"""Verbs In Context System (Walker) -- operational code indices.

Consolidates the 12 stand-alone Q*.py scripts into one module that shares a
loader and phrase-aware matching. Formulas are preserved from the originals;
two robustness fixes are applied throughout:
  * divide-by-zero is guarded (several originals crash on empty categories);
  * matching is phrase-aware (the originals' single-token Counter silently
    missed any multi-word list entry), so values can differ slightly -- more
    correctly -- from the original scripts.

Word lists are read in place from "VICS Code/VICS Code/..."; nothing is copied.
"""
from __future__ import annotations

import os

from .dictionaries import VICS_DIR, load_txt_wordlist
from .text_utils import count_matches

QP = os.path.join(VICS_DIR, "QP")
QI = os.path.join(VICS_DIR, "QI")

# Tactic categories shared by P-2, I-2, I-5 with their VICS weights.
_TACTIC_FILES = {
    "Punish": ("Punish.txt", -3),
    "Threaten": ("Threaten.txt", -2),
    "Oppose": ("Oppose-Resist.txt", -1),
    "Neutral": ("Neutral.txt", 0),
    "Appeal": ("Appeal-Support.txt", 1),
    "Promise": ("Promise.txt", 2),
    "Reward": ("Reward.txt", 3),
}


def _load(*parts: str) -> set[str]:
    return load_txt_wordlist(os.path.join(*parts))


def _counts(text: str, words: set[str]) -> int:
    return count_matches(text, words)[0]


def _iqv_predictability(a: int, b: int) -> float:
    """1 - IQV over a 2-category split (used by P-3 and I-3)."""
    t = a + b
    if not t:
        return 0.0
    iqv = 2 * (1 - (a / t) ** 2 - (b / t) ** 2)
    return 1 - iqv


def _tactic_counts(text: str, folder: str) -> dict[str, int]:
    return {
        name: _counts(text, _load(folder, fname))
        for name, (fname, _w) in _TACTIC_FILES.items()
    }


def _weighted_tactics_index(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    if not total:
        return 0.0
    neg = (counts["Punish"] * -3 + counts["Threaten"] * -2 + counts["Oppose"] * -1) / 3
    pos = (counts["Appeal"] * 1 + counts["Promise"] * 2 + counts["Reward"] * 3) / 3
    return (pos + neg) / total


# --------------------------------------------------------------------------- #
# Philosophical (P) indices
# --------------------------------------------------------------------------- #
def p1_nature_of_universe(text: str) -> dict:
    pos = _counts(text, _load(QP, "Q1P_txt", "positive_words.txt"))
    neg = _counts(text, _load(QP, "Q1P_txt", "negative_words.txt"))
    t = pos + neg
    return {"label": "P-1 Nature of Political Universe",
            "positive": pos, "negative": neg,
            "value": (pos - neg) / t if t else 0.0}


def p2_realisation_of_values(text: str) -> dict:
    counts = _tactic_counts(text, os.path.join(QP, "Q2P_txt"))
    return {"label": "P-2 Realisation of Political Values",
            "counts": counts, "value": _weighted_tactics_index(counts)}


def p3_predictability(text: str) -> dict:
    intern = _counts(text, _load(QP, "Q3P_txt", "Internal_locus.txt"))
    extern = _counts(text, _load(QP, "Q3P_txt", "External_locus.txt"))
    return {"label": "P-3 Predictability of Political Future",
            "internal": intern, "external": extern,
            "value": _iqv_predictability(intern, extern)}


def p4_control_over_history(text: str) -> dict:
    s = _counts(text, _load(QP, "Q4P_txt", "self_attributions.txt"))
    o = _counts(text, _load(QP, "Q4P_txt", "other_attributions.txt"))
    t = s + o
    return {"label": "P-4 Control over Historical Development",
            "self": s, "other": o, "value": s / t if t else 0.0}


def p5_role_of_chance(text: str) -> dict:
    predictability = p3_predictability(text)["value"]
    control = p4_control_over_history(text)["value"]
    return {"label": "P-5 Role of Chance",
            "value": 1 - (predictability * control)}


# --------------------------------------------------------------------------- #
# Instrumental (I) indices
# --------------------------------------------------------------------------- #
_Q1I = os.path.join(QI, "Q1I_txt", "Lists Q1I")


def i1_direction_of_strategy(text: str) -> dict:
    pos = _counts(text, _load(_Q1I, "positive_self_attributions.txt"))
    neg = _counts(text, _load(_Q1I, "negative_self_attributions.txt"))
    t = pos + neg
    return {"label": "I-1 Direction of Strategy",
            "positive": pos, "negative": neg,
            "value": (pos - neg) / t if t else 0.0}


def i2_intensity_of_tactics(text: str) -> dict:
    counts = _tactic_counts(text, os.path.join(QI, "Q2I_txt", "Lists Q2I"))
    return {"label": "I-2 Intensity of Tactics",
            "counts": counts, "value": _weighted_tactics_index(counts)}


def i3_risk_orientation(text: str) -> dict:
    acc = _counts(text, _load(QI, "Q3I_txt", "Lists Q3I", "risk_acceptant.txt"))
    ave = _counts(text, _load(QI, "Q3I_txt", "Lists Q3I", "risk_averse.txt"))
    return {"label": "I-3 Risk Orientation",
            "acceptant": acc, "averse": ave,
            "value": _iqv_predictability(acc, ave)}


def i4a_shift_cooperation_conflict(text: str) -> dict:
    pos = _counts(text, _load(QI, "Q4aI_txt", "Lists Q4I", "positive_words.txt"))
    neg = _counts(text, _load(QI, "Q4aI_txt", "Lists Q4I", "negative_words.txt"))
    t = pos + neg
    pd = abs(pos / t - neg / t) if t else 0.0
    return {"label": "I-4a Timing: Cooperation/Conflict",
            "positive": pos, "negative": neg, "value": 1 - pd}


def i4b_shift_words_deeds(text: str) -> dict:
    deeds = _counts(text, _load(QI, "Q4bI_txt", "deeds.txt"))
    words = _counts(text, _load(QI, "Q4bI_txt", "words.txt"))  # may be missing
    t = deeds + words
    pd = abs(words / t - deeds / t) if t else 0.0
    out = {"label": "I-4b Timing: Words/Deeds",
           "deeds": deeds, "words": words, "value": 1 - pd}
    if not os.path.exists(os.path.join(QI, "Q4bI_txt", "words.txt")):
        out["warning"] = "words.txt missing; value reflects deeds only"
    return out


def i5_distribution_of_tactics(text: str) -> dict:
    counts = _tactic_counts(text, os.path.join(QI, "Q5I_txt"))
    total = sum(counts.values()) or 1
    return {"label": "I-5 Distribution of Tactics",
            "counts": counts,
            "distribution": {k: v / total for k, v in counts.items()}}


def summary_index(text: str) -> dict:
    """Combined self-vs-other attribution index from Summary.py."""
    pos_self = _counts(text, _load(_Q1I, "positive_self_attributions.txt"))
    neg_self = _counts(text, _load(_Q1I, "negative_self_attributions.txt"))
    pos_oth = _counts(text, _load(QP, "Q1P_txt", "positive_words.txt"))
    neg_oth = _counts(text, _load(QP, "Q1P_txt", "negative_words.txt"))
    ts = pos_self + neg_self
    to = pos_oth + neg_oth
    self_term = (pos_self - neg_self) / ts if ts else 0.0
    oth_term = (pos_oth - neg_oth) / to if to else 0.0
    return {"label": "Summary (self vs other)",
            "value": (self_term - oth_term) / 2}


def score_vics(text: str) -> dict:
    """Run every VICS index and return a structured, JSON-friendly result."""
    return {
        "P-1": p1_nature_of_universe(text),
        "P-2": p2_realisation_of_values(text),
        "P-3": p3_predictability(text),
        "P-4": p4_control_over_history(text),
        "P-5": p5_role_of_chance(text),
        "I-1": i1_direction_of_strategy(text),
        "I-2": i2_intensity_of_tactics(text),
        "I-3": i3_risk_orientation(text),
        "I-4a": i4a_shift_cooperation_conflict(text),
        "I-4b": i4b_shift_words_deeds(text),
        "I-5": i5_distribution_of_tactics(text),
        "Summary": summary_index(text),
    }


if __name__ == "__main__":
    with open(os.path.join(VICS_DIR, "input_text.txt"), encoding="utf-8") as fh:
        sample = fh.read()
    for code, res in score_vics(sample).items():
        if "value" in res:
            print(f"  {code:8} {res['label']:42} {res['value']:.3f}")
        else:
            print(f"  {code:8} {res['label']}")
