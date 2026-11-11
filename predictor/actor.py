"""Who does the action: rules that keep other people's actions out of BACE and PWR.

Hermann codes BACE and PWR only where the speaker, or the speaker's group, is the
one acting. A word counter can't tell "I ended seven wars" from "They helped build
this country", or "We will control it" from "We cannot control it". These rules read
the grammar of each counted word and give it a role:

    "self"   the speaker or their group acts: I, we, my government, our country
    "other"  someone else acts: they, he, you, China, the people who built...
    "denied" the speaker's action is negated: not, never, cannot, failed to, unable to
    ""       no evidence either way (no subject found): counted, as before

Only "other" and "denied" are left out of the count, so a word is dropped only when
the sentence shows why. No AI model is involved: English uses spaCy's grammatical
parser (a fixed, standard parse of subject, object and negation) and Arabic uses
verb endings and nearby particles. Every decision can be traced to a rule below.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# English
# --------------------------------------------------------------------------- #
_SELF = {"i", "we", "me", "us", "myself", "ourselves"}
_SELF_POSS = {"my", "our"}
_OTHER_POSS = {"his", "her", "their", "your", "its"}
_REL = {"who", "that", "which"}
_NEG = {"not", "n't", "never", "no", "neither", "nor", "cannot"}
# "We failed to deliver", "unable to control": the action didn't happen.
_DENY_HEADS = {"fail", "refuse", "unable", "decline", "cease"}
# Clause links whose verb shares its subject with the verb above it:
# "we want to BUILD" (xcomp), "we built and EXPANDED" (conj), "we worked to BUILD" (advcl).
_SHARED_SUBJECT = {"xcomp", "conj", "advcl"}


def _negated(tok) -> bool:
    for c in tok.children:
        if c.dep_ == "neg" or c.lower_ in _NEG and c.dep_ in ("advmod", "aux", "neg"):
            return True
        # "Never again will we...": the "never" hangs off "again".
        if c.dep_ == "advmod" and any(g.dep_ == "neg" for g in c.children):
            return True
    return False


def _person(subj) -> str:
    """'self' or 'other' for a subject word."""
    low = subj.lower_
    if low in _SELF:
        return "self"
    if any(c.dep_ == "poss" and c.lower_ in _SELF_POSS for c in subj.children):
        return "self"  # my administration, our country
    # "all of us", "each of us", "many of us"
    for c in subj.children:
        if c.dep_ == "prep" and c.lower_ == "of" and any(
                g.dep_ == "pobj" and g.lower_ in _SELF for g in c.children):
            return "self"
    # "we and our allies": the speaker is one of the actors.
    if any(c.dep_ == "conj" and c.lower_ in _SELF for c in subj.children):
        return "self"
    return "other"


def _verb_role(verb) -> str:
    node, denied, steps = verb, False, 0
    while node is not None and steps < 8:
        if _negated(node) or (node is not verb and node.lemma_.lower() in _DENY_HEADS):
            denied = True
        subjects = [c for c in node.children if c.dep_ in ("nsubj", "csubj", "expl")]
        agents = [g for c in node.children if c.dep_ == "agent"
                  for g in c.children if g.dep_ == "pobj"]
        if agents:  # passive with "by ...": "the wall was built by them"
            subjects = agents
        elif any(c.dep_ in ("nsubjpass", "csubjpass") for c in node.children):
            return "denied" if denied else ""  # passive, actor not named
        if subjects:
            subj = subjects[0]
            if subj.lower_ in _REL and node.dep_ == "relcl":
                subj = node.head  # "the people WHO built": the people built
            if subj.dep_ == "expl":
                return "denied" if denied else ""
            if _person(subj) == "other":
                return "other"
            return "denied" if denied else "self"
        if node.dep_ in _SHARED_SUBJECT and node.head is not node:
            node, steps = node.head, steps + 1
            continue
        break
    return "denied" if denied else ""


def _noun_role(noun) -> str:
    """'our capability' is the speaker's, 'their leadership' someone else's."""
    for c in noun.children:
        if c.dep_ != "poss":
            continue
        if c.lower_ in _SELF_POSS:
            return "self"
        if c.lower_ in _OTHER_POSS or c.pos_ in ("PROPN", "NOUN"):
            return "other"
    return ""


def en_role(tok) -> str:
    """The role of one spaCy token (see the module docstring)."""
    if tok.pos_ in ("VERB", "AUX"):
        return _verb_role(tok)
    if tok.pos_ in ("NOUN", "PROPN"):
        return _noun_role(tok)
    return ""


# --------------------------------------------------------------------------- #
# Arabic (normalized tokens, as predictor.arabic.tokens)
# --------------------------------------------------------------------------- #
# No grammatical parser is available, so Arabic uses what the verb itself shows:
# its person ending, a pronoun just before it, or a negation particle.
_AR_NEG = {"لا", "لم", "لن", "ما", "ليس", "لست", "لسنا", "ليسوا", "مش", "مو", "غير"}
_AR_OTHER_PRON = {"هم", "هو", "هي", "هن", "هما", "انتم", "انت", "انتي", "انتن"}
_AR_SELF_PRON = {"نحن", "انا", "احنا"}
_AR_PREFIX = ("و", "ف")


def _peel(tok: str) -> str:
    for p in _AR_PREFIX:
        if tok.startswith(p) and len(tok) > 3:
            return tok[len(p):]
    return tok


def ar_role(toks: list[str], i: int, j: int, entry: str) -> str:
    """Role of the hit toks[i..j] for lexicon entry `entry` (normalized forms)."""
    tok = _peel(toks[i])
    before = [_peel(t) for t in toks[max(0, i - 2):i]]
    # Egyptian "ما...ش" around the verb: "مابنيناش" = we didn't build.
    if tok.startswith("ما") and tok.endswith("ش") and len(tok) > 4:
        return "denied"
    if before:
        neg = before[-1]
        # "ما حققناه" is "what we achieved", not a negation.
        if neg in _AR_NEG and not (neg == "ما" and tok.endswith(("ه", "ها"))):
            return "denied"
        # "لم نستطع أن نبني": the negation sits on the helper verb before "أن".
        if before[-1] == "ان" and i >= 3 and _peel(toks[i - 3]) in _AR_NEG:
            return "denied"
    if any(b in _AR_OTHER_PRON for b in before):
        return "other"
    if any(b in _AR_SELF_PRON for b in before):
        return "self"
    base = entry.replace(" ", "")
    # They: يبنون / بيبنوا / بنوا / سيحققون. Kept only when the entry itself doesn't
    # end that way, so a noun like "قانون" is never mistaken for a verb ending.
    stem = tok[1:] if tok.startswith(("س", "ب", "ه", "ح")) and len(tok) > 4 else tok
    if not base.endswith(("ون", "وا")):
        if stem.startswith(("ي", "ت")) and stem.endswith(("ون", "وا")) and len(stem) > 4:
            return "other"
        if tok.endswith("وا") and len(tok) > 3 and not tok.startswith(("ن", "ا")):
            return "other"
    # Their: قدراتهم, سيطرتهم ("their capability", "their control").
    if tok.endswith("هم") and not base.endswith("هم") and len(tok) > len(base):
        return "other"
    # We: نبني / بنبني / حققنا / سنحقق.
    if stem.startswith("ن") or tok.endswith(("نا", "ناه", "ناها", "ناهم")):
        return "self"
    return ""
