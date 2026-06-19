"""spaCy-backed lemmatization + POS, for faithful LTA matching.

Exact string matching missed inflected forms (possibilities != possibility) and
couldn't tell a verb from a noun ("a plan" vs "to plan"). This layer lemmatizes
both the text and the dictionary phrases and exposes part-of-speech, so:
  * word variants match (lemma-based);
  * BACE/PWR can count verbs only, TASK nouns only, as Hermann's coding intends.
"""
from __future__ import annotations

from functools import lru_cache

import spacy

_MODEL = "en_core_web_sm"
_NLP = None


def nlp():
    """Lazily load the spaCy pipeline (parser/NER disabled for speed)."""
    global _NLP
    if _NLP is None:
        _NLP = spacy.load(_MODEL, disable=["parser", "ner"])
    return _NLP


@lru_cache(maxsize=512)
def doc_tokens(text: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Tokenize once; return (surfaces, lemmas, pos_tags) skipping space/punct.

    Cached by text so scoring all seven traits on one speech parses it once.
    """
    doc = nlp()(text)
    surfaces, lemmas, pos = [], [], []
    for t in doc:
        if t.is_space or t.is_punct:
            continue
        surfaces.append(t.text.lower())
        lemmas.append(t.lemma_.lower())
        pos.append(t.pos_)
    return tuple(surfaces), tuple(lemmas), tuple(pos)


def content_token_count(text: str) -> int:
    """Denominator for densities: non-space, non-punct tokens."""
    return len(doc_tokens(text)[1])


@lru_cache(maxsize=64)
def compile_phrases(phrases: frozenset[str]) -> tuple[dict, tuple]:
    """Lemmatize a dictionary into (single-lemma map, multi-lemma phrase list).

    single: {lemma: original_phrase}; multi: ((lemma, lemma, ...), original).
    """
    single: dict[str, str] = {}
    multi: list[tuple[tuple[str, ...], str]] = []
    pipe = nlp()
    for phrase in phrases:
        lemmas = tuple(t.lemma_.lower() for t in pipe(phrase)
                       if not t.is_punct and not t.is_space)
        if len(lemmas) == 1:
            single[lemmas[0]] = phrase
        elif len(lemmas) > 1:
            multi.append((lemmas, phrase))
    return single, tuple(multi)


def count_lemma(text: str, phrases: frozenset[str],
                allowed_pos: frozenset[str] | None = None
                ) -> tuple[int, dict[str, int]]:
    """Count dictionary hits by lemma, optionally restricted to a POS set.

    Single-word entries respect `allowed_pos`; multi-word phrases match on the
    lemma sequence (POS not filtered for phrases).
    """
    surfaces, lemmas, pos = doc_tokens(text)
    single, multi = compile_phrases(phrases)
    hits: dict[str, int] = {}
    total = 0
    for i, lem in enumerate(lemmas):
        if lem in single and (allowed_pos is None or pos[i] in allowed_pos):
            p = single[lem]
            hits[p] = hits.get(p, 0) + 1
            total += 1
    n = len(lemmas)
    for lemtup, p in multi:
        L = len(lemtup)
        for i in range(n - L + 1):
            if lemmas[i:i + L] == lemtup:
                hits[p] = hits.get(p, 0) + 1
                total += 1
    return total, hits


def count_surface(text: str, words: frozenset[str]) -> tuple[int, dict[str, int]]:
    """Count by surface form (for closed-class pronoun lists like SC)."""
    surfaces, _lemmas, _pos = doc_tokens(text)
    hits: dict[str, int] = {}
    total = 0
    for s in surfaces:
        if s in words:
            hits[s] = hits.get(s, 0) + 1
            total += 1
    return total, hits
