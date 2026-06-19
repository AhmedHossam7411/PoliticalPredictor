"""Leadership Trait Analysis (Hermann) -- simplified dictionary scoring.

Seven traits: BACE, PWR, CC, SC, TASK, DIS, IGB.

Note on method: the shipped dictionaries are bag-of-words, so this is a
simplified version of Hermann's coding (which scores BACE/PWR on verbs only,
DIS on nouns referring to others, etc.). Two traits have a natural paired
denominator and yield a true 0..1 ratio:
    CC   = high / (high + low)
    TASK = task / (task + group-maintenance)
The other five are reported as a density (matches per 1000 tokens); High/Mod/Low
for those is decided later by comparison to a norming group -- exactly as
Hermann assigns High/Low relative to a sample of leaders, not on an absolute.
"""
from __future__ import annotations

from .dictionaries import lta_dictionaries
from .text_utils import count_matches, token_count

TRAITS = ("BACE", "PWR", "CC", "SC", "TASK", "DIS", "IGB")

# Which traits are true ratios vs densities (affects how they are normed/displayed).
RATIO_TRAITS = ("CC", "TASK")
DENSITY_TRAITS = ("BACE", "PWR", "SC", "DIS", "IGB")


def score_lta(text: str) -> dict:
    """Return raw LTA metrics for one text.

    Each trait entry has: raw count(s), a 'value' (ratio for CC/TASK, density
    per-1000-tokens otherwise), and the matched phrases for transparency.
    """
    d = lta_dictionaries()
    tokens = token_count(text) or 1  # guard divide-by-zero
    out: dict = {"tokens": tokens, "traits": {}}

    def density(count: int) -> float:
        return 1000.0 * count / tokens

    # --- Conceptual Complexity: high vs low complexity markers (true ratio).
    high_n, high_hits = count_matches(text, d["CC_high"])
    low_n, low_hits = count_matches(text, d["CC_low"])
    cc_total = high_n + low_n
    out["traits"]["CC"] = {
        "kind": "ratio",
        "high": high_n,
        "low": low_n,
        "value": (high_n / cc_total) if cc_total else 0.5,
        "matches": {"high": high_hits, "low": low_hits},
    }

    # --- Task focus: task vs group-maintenance words (true ratio).
    task_n, task_hits = count_matches(text, d["TASK"])
    grp_n, grp_hits = count_matches(text, d["TASK_group"])
    task_total = task_n + grp_n
    out["traits"]["TASK"] = {
        "kind": "ratio",
        "task": task_n,
        "group": grp_n,
        "value": (task_n / task_total) if task_total else 0.5,
        "matches": {"task": task_hits, "group": grp_hits},
        "seeded": True,  # dictionary seeded from the manual, not shipped
    }

    # --- Density traits (single list each).
    for trait, key in (("BACE", "BACE"), ("PWR", "PWR"), ("SC", "SC"),
                       ("DIS", "DIS"), ("IGB", "IGB")):
        n, hits = count_matches(text, d[key])
        out["traits"][trait] = {
            "kind": "density",
            "count": n,
            "value": density(n),  # per 1000 tokens
            "matches": hits,
        }

    return out


if __name__ == "__main__":
    sample = (
        "We will defend our people. However, the situation is complex and "
        "depends on many factors. I believe I can shape these events. Perhaps "
        "we must achieve our objective and implement our plan together."
    )
    import json
    result = score_lta(sample)
    print(f"tokens={result['tokens']}")
    for t in TRAITS:
        tr = result["traits"][t]
        print(f"  {t:5} value={tr['value']:.3f}  ({tr['kind']})")
