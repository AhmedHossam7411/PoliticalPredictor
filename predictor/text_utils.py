"""Shared tokenizing / phrase-matching helpers.

The LTA dictionaries contain multi-word phrases (e.g. "on the other hand",
"take charge"). A single-token Counter -- as the original VICS scripts use --
silently misses those, so matching must be phrase-aware.
"""
from __future__ import annotations

import re
from functools import lru_cache

_TOKEN = re.compile(r"\b\w+\b")


def token_count(text: str) -> int:
    """Number of word tokens in the text (the denominator for densities)."""
    return len(_TOKEN.findall(text))


@lru_cache(maxsize=4096)
def _phrase_pattern(phrase: str) -> re.Pattern:
    # Join words with flexible whitespace; anchor on word boundaries.
    parts = [re.escape(w) for w in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE)


def count_matches(text: str, phrases: set[str]) -> tuple[int, dict[str, int]]:
    """Count non-overlapping occurrences of each phrase in text.

    Returns (total_hits, {phrase: count}) including only phrases that matched.
    """
    hits: dict[str, int] = {}
    total = 0
    for phrase in phrases:
        n = len(_phrase_pattern(phrase).findall(text))
        if n:
            hits[phrase] = n
            total += n
    return total, hits
