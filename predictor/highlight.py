"""Character spans of every word the LTA dictionary scorer counts.

Mirrors predictor.lta.score_lta exactly (same lexicons, same matching rules),
but keeps each hit's position so it can be highlighted. `check_counts` asserts
the totals agree with the real scorer, so the highlights can't drift from it.

Labels are "<trait>:<pole>": CC and SC :high / :low, TASK:high (problem-solving
words) / TASK:low (relationship words), and BACE/PWR/DIS/IGB:high. A BACE or PWR
word the scorer left out is BACE:other (someone else acts) or BACE:denied.
"""
from __future__ import annotations

import re

from . import arabic
from .dictionaries import lta_dictionaries, lta_dictionaries_ar
from .lta import score_lta
from .actor import ar_role
from .lta import AGENCY_TRAITS
from .nlp import SKIPPED, kept_tokens, lemma_hits, token_roles

# Lexicon -> highlight label, in the order the scorer uses them.
LISTS = {
    "CC_high": "CC:high", "CC_low": "CC:low",
    "SC_high": "SC:high", "SC_low": "SC:low",
    "TASK": "TASK:high", "TASK_group": "TASK:low",
    "BACE": "BACE:high", "PWR": "PWR:high",
    "DIS": "DIS:high", "IGB": "IGB:high",
}

# --------------------------------------------------------------------------- #
# English: spaCy tokens with character offsets (as predictor.nlp.doc_tokens).
# --------------------------------------------------------------------------- #
def _label(label: str, role: str) -> str:
    """BACE:high becomes BACE:other / BACE:denied when the scorer left the word out."""
    trait = label.split(":")[0]
    return f"{trait}:{role}" if trait in AGENCY_TRAITS and role in SKIPPED else label


def _en_spans(text: str) -> list[dict]:
    toks = kept_tokens(text)
    roles = token_roles(text)
    d = lta_dictionaries()
    spans = []
    for key, label in LISTS.items():
        for i, j, _ in lemma_hits(text, frozenset(d[key])):
            role = next((roles[k] for k in range(i, j + 1) if roles[k]), "")
            spans.append({"start": toks[i].idx, "end": toks[j].idx + len(toks[j].text),
                          "labels": [_label(label, role)]})
    return spans


# --------------------------------------------------------------------------- #
# Arabic: tokens as predictor.arabic.tokens, but located in the original text.
# --------------------------------------------------------------------------- #
# A raw word: Arabic letters plus anything normalize() strips or folds.
_AR_RAW = re.compile("[ء-يٱکی"          # letters (incl. ـ)
                     "ؐ-ًؚ-ٰٟۖ-ۭ]+")  # diacritics


def _ar_tokens(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _AR_RAW.finditer(text):
        # normalize() can't split a raw word except at a folded-away char; map
        # each normalized piece back onto the raw word's span.
        for piece in arabic.tokens(m.group()):
            out.append((m.start(), m.end(), piece))
    return out


def _ar_spans(text: str) -> list[dict]:
    toks = _ar_tokens(text)
    d = lta_dictionaries_ar()
    spans = []
    words = [t[2] for t in toks]
    for key, label in LISTS.items():
        spans += [{"start": toks[i][0], "end": toks[j][1],
                   "labels": [_label(label, ar_role(words, i, j, " ".join(arabic.tokens(e))))]}
                  for i, j, e in arabic.term_hits(words, frozenset(d[key]))]
    return spans


def scorer_spans(text: str) -> list[dict]:
    """Every dictionary hit as {start, end, labels}; one entry per counted hit."""
    return _ar_spans(text) if arabic.is_arabic(text) else _en_spans(text)


def check_counts(text: str, spans: list[dict]) -> dict[str, tuple[int, int]]:
    """{label: (highlighted, scorer count)} for any label where they disagree."""
    tr = score_lta(text)["traits"]
    expected = {
        "CC:high": tr["CC"]["high"], "CC:low": tr["CC"]["low"],
        "SC:high": tr["SC"]["high"], "SC:low": tr["SC"]["low"],
        "TASK:high": tr["TASK"]["task"], "TASK:low": tr["TASK"]["group"],
        **{f"{t}:high": tr[t]["count"] for t in ("BACE", "PWR", "DIS", "IGB")},
        **{f"{t}:{r}": tr[t]["skipped"][r] for t in AGENCY_TRAITS for r in SKIPPED},
    }
    got = {k: 0 for k in expected}
    for sp in spans:
        for lab in sp["labels"]:
            got[lab] += 1
    return {k: (got[k], v) for k, v in expected.items() if got[k] != v}
