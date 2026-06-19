"""Leadership Trait Analysis (Hermann) -- lemma + POS dictionary scoring.

Seven traits: BACE, PWR, CC, SC, TASK, DIS, IGB.

Matching is lemma-based (so "possibilities" matches "possibility") with
part-of-speech filters that follow Hermann's coding intent:
    BACE, PWR -> verbs only (agency / influence as action)
    TASK      -> nouns only  (work/goal nouns; this also splits the heavy
                              BACE/TASK list overlap: "to plan" vs "a plan")
    DIS       -> nouns + adjectives (threats and suspicious descriptors)
    SC        -> surface pronouns (closed class)
    CC, IGB   -> any POS (markers/identity terms span several classes)

Two traits are true ratios; the rest are densities (per 1000 tokens), with
High/Moderate/Low assigned later relative to a norming group.
"""
from __future__ import annotations

from .dictionaries import lta_dictionaries
from .nlp import count_lemma, count_surface, content_token_count

TRAITS = ("BACE", "PWR", "CC", "SC", "TASK", "DIS", "IGB")
RATIO_TRAITS = ("CC", "TASK")
DENSITY_TRAITS = ("BACE", "PWR", "SC", "DIS", "IGB")

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


def score_lta(text: str) -> dict:
    """Return raw LTA metrics for one text (lemma + POS based)."""
    d = lta_dictionaries()
    tokens = content_token_count(text) or 1
    out: dict = {"tokens": tokens, "traits": {}}

    def density(count: int) -> float:
        return 1000.0 * count / tokens

    # --- Conceptual Complexity: high vs low markers (ratio, any POS).
    high_n, high_hits = count_lemma(text, _fs(d["CC_high"]))
    low_n, low_hits = count_lemma(text, _fs(d["CC_low"]))
    cc_total = high_n + low_n
    out["traits"]["CC"] = {
        "kind": "ratio", "high": high_n, "low": low_n,
        "value": (high_n / cc_total) if cc_total else 0.5,
        "matches": {"high": high_hits, "low": low_hits},
    }

    # --- Task focus: task nouns vs group-maintenance words (ratio).
    task_n, task_hits = count_lemma(text, _fs(d["TASK"]), _pos_for("TASK"))
    grp_n, grp_hits = count_lemma(text, _fs(d["TASK_group"]))
    task_total = task_n + grp_n
    out["traits"]["TASK"] = {
        "kind": "ratio", "task": task_n, "group": grp_n,
        "value": (task_n / task_total) if task_total else 0.5,
        "matches": {"task": task_hits, "group": grp_hits},
    }

    # --- Self-confidence: surface pronouns (density).
    sc_n, sc_hits = count_surface(text, _fs(d["SC"]))
    out["traits"]["SC"] = {"kind": "density", "count": sc_n,
                           "value": density(sc_n), "matches": sc_hits}

    # --- Remaining density traits (verbs for BACE/PWR, noun/adj for DIS, any IGB).
    for trait in ("BACE", "PWR", "DIS", "IGB"):
        n, hits = count_lemma(text, _fs(d[trait]), _pos_for(trait))
        out["traits"][trait] = {"kind": "density", "count": n,
                                "value": density(n), "matches": hits}

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
