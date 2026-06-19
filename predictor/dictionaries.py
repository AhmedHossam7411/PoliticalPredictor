"""Dictionary loading for both methodologies.

LTA word lists are stored as macOS RTF files (one phrase per line).
VICS word lists are plain .txt files (one phrase per line).
This module turns both into clean Python sets and exposes a registry so the
scorers don't hard-code file paths.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

# Repo root = parent of this package directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LTA_DIR = os.path.join(ROOT, "LTA Code", "LTA Code")
VICS_DIR = os.path.join(ROOT, "VICS Code", "VICS Code")

# Lines whose presence means the line is RTF structure, not content.
_RTF_STRUCTURE_TOKENS = (
    "\\rtf1", "fonttbl", "colortbl", "expandedcolortbl",
    "paperw", "pardeftab", "pardirnatural", "deftab",
)
_RTF_CONTROL_WORD = re.compile(r"\\[a-zA-Z]+-?[0-9]*\s?")
_RTF_HEX_ESCAPE = re.compile(r"\\'[0-9a-fA-F]{2}")


def _clean_phrase(phrase: str) -> str:
    return phrase.strip().lower()


def load_rtf_wordlist(path: str) -> set[str]:
    """Parse a macOS RTF word list into a set of lower-cased phrases.

    The files put one entry per line, each ending in a literal backslash, with
    RTF control words sprinkled on the first content line and between blocks.
    We strip control words/escapes/braces line-by-line and keep what's left.
    """
    words: set[str] = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if any(tok in line for tok in _RTF_STRUCTURE_TOKENS):
                continue
            line = _RTF_HEX_ESCAPE.sub("", line)
            line = _RTF_CONTROL_WORD.sub("", line)
            line = line.replace("\\", "").replace("{", "").replace("}", "")
            phrase = _clean_phrase(line)
            if phrase and ";" not in phrase:
                words.add(phrase)
    return words


def load_txt_wordlist(path: str) -> set[str]:
    """Parse a plain-text word list (VICS) into a set of lower-cased phrases."""
    words: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                phrase = _clean_phrase(line)
                if phrase:
                    words.add(phrase)
    except FileNotFoundError:
        print(f"Warning: word list not found - {path}")
    return words


# --- TASK focus: no dictionary shipped with the project, so seed one from the
# examples Hermann gives in the LTA manual (task-oriented vs group-maintenance).
TASK_WORDS = {
    "accomplishment", "accomplish", "achieve", "achievement", "plan", "planning",
    "position", "proposal", "propose", "recommendation", "recommend", "tactic",
    "strategy", "objective", "goal", "implement", "implementation", "solution",
    "solve", "result", "performance", "efficiency", "productivity", "build",
    "construct", "develop", "production", "complete", "execute", "deliver",
}
GROUP_MAINTENANCE_WORDS = {
    "appreciation", "appreciate", "amnesty", "collaboration", "collaborate",
    "disappoint", "disappointment", "forgive", "forgiveness", "harm", "liberation",
    "liberate", "suffering", "suffer", "loyalty", "morale", "spirit", "trust",
    "togetherness", "unity", "compassion", "care", "support", "empathy", "comfort",
    "reconcile", "reconciliation", "harmony", "wellbeing", "feelings",
}


# Registry: maps a logical dictionary name to its loaded set.
@lru_cache(maxsize=1)
def lta_dictionaries() -> dict[str, set[str]]:
    """Load all LTA trait dictionaries. Cached after first call."""
    return {
        "BACE": load_rtf_wordlist(os.path.join(LTA_DIR, "B.O.C.E.rtf")),
        "PWR": load_rtf_wordlist(os.path.join(LTA_DIR, "N.F.P Sub1.rtf")),
        "CC_high": load_rtf_wordlist(os.path.join(LTA_DIR, "high CC.rtf")),
        "CC_low": load_rtf_wordlist(os.path.join(LTA_DIR, "Low CC.rtf")),
        "SC": load_rtf_wordlist(os.path.join(LTA_DIR, "S.C.rtf")),
        "DIS": load_rtf_wordlist(os.path.join(LTA_DIR, "DTOO.rtf")),
        "IGB": load_rtf_wordlist(os.path.join(LTA_DIR, "IGB .rtf")),
        "TASK": TASK_WORDS,
        "TASK_group": GROUP_MAINTENANCE_WORDS,
    }


if __name__ == "__main__":
    for name, words in lta_dictionaries().items():
        sample = sorted(words)[:5]
        print(f"{name:12} {len(words):3} entries  e.g. {sample}")
