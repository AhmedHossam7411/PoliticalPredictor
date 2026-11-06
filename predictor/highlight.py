"""Character spans of every word the LTA dictionary scorer counts.

Mirrors predictor.lta.score_lta exactly (same lexicons, same matching rules),
but keeps each hit's position so it can be highlighted. `check_counts` asserts
the totals agree with the real scorer, so the highlights can't drift from it.

Labels are "<trait>:<pole>": CC and SC :high / :low, TASK:high (problem-solving
words) / TASK:low (relationship words), and BACE/PWR/DIS/IGB:high.
"""
from __future__ import annotations

import re

from . import arabic
from .dictionaries import lta_dictionaries, lta_dictionaries_ar
from .lta import score_lta
from .nlp import compile_phrases, nlp, single_hit

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
def _en_tokens(text: str) -> list[tuple[int, int, str, str, str]]:
    """(start, end, lowercase surface, lemma, POS), skipping spaces and punctuation."""
    return [(t.idx, t.idx + len(t.text), t.text.lower(), t.lemma_.lower(), t.pos_)
            for t in nlp()(text) if not (t.is_space or t.is_punct)]


def _en_spans(text: str) -> list[dict]:
    toks = _en_tokens(text)
    d = lta_dictionaries()
    spans = []
    for key, label in LISTS.items():
        words = frozenset(d[key])
        single, multi = compile_phrases(words)  # count_lemma
        spans += [{"start": s, "end": e, "labels": [label]}
                  for s, e, surf, lem, pos in toks if single_hit(surf, lem, pos, single)]
        lemmas = [t[3] for t in toks]
        for lemtup, _phrase in multi:
            n = len(lemtup)
            for i in range(len(toks) - n + 1):
                if tuple(lemmas[i:i + n]) == lemtup:
                    spans.append({"start": toks[i][0], "end": toks[i + n - 1][1],
                                  "labels": [label]})
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
    for key, label in LISTS.items():
        words = [t[2] for t in toks]
        spans += [{"start": toks[i][0], "end": toks[j][1], "labels": [label]}
                  for i, j, _ in arabic.term_hits(words, frozenset(d[key]))]
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
    }
    got = {k: 0 for k in expected}
    for sp in spans:
        for lab in sp["labels"]:
            got[lab] += 1
    return {k: (got[k], v) for k, v in expected.items() if got[k] != v}
