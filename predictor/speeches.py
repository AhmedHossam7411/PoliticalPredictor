"""Split a document holding several speakers into one text per speaker.

UN records and similar transcripts open each turn with a labelled line:
    President Obama: ...
    Mr. Brown (United Kingdom): ...
    Colonel Al-Qadhafi (spoke in Arabic): ...
    The President (spoke in Arabic): ...
    السيد براون (المملكة المتحدة): ...
A profile only means something for one person, so each speaker gets their own
text. Speeches with no speaker label can't be told apart and stay together.
"""
from __future__ import annotations

import re

_NOTES = r"(?P<notes>(?:\([^()]*\)\s*)*)"

_EN_TITLES = (r"President|Vice[- ]President|Prime[ \t]+Minister|Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|Sir|Lord|Lady"
              r"|King|Queen|Prince|Princess|Sheikh|Sheikha|Sultan|Amir|Emir|Colonel|General|Marshal"
              r"|Chancellor|Minister|Archbishop|Cardinal|Senator|Judge|Justice")
_EN_ROLES = (r"The[ \t]+(?:Acting[ \t]+|Temporary[ \t]+)?President|The[ \t]+Chair(?:man|person)?"
             r"|The[ \t]+(?:Acting[ \t]+)?Secretary-General|The[ \t]+Prime[ \t]+Minister|The[ \t]+Speaker")
_EN_NAME = r"(?:[A-ZÀ-ÖØ-Þ][\w'’.\-]*|da|de|del|di|bin|ibn|al|el|van|von)"
_EN_MARKER = re.compile(
    rf"^[ \t]*(?P<who>{_EN_ROLES}|(?:{_EN_TITLES})(?:[ \t]+{_EN_NAME}){{1,5}})[ \t]*{_NOTES}:", re.M)

_AR_ROLES = "الرئيس(?:ة)?(?:[ \t]+بالنيابة|[ \t]+المؤقت)?|الأمين[ \t]+العام"
_AR_TITLES = ("الرئيس|الرئيسة|رئيس[ \t]+الوزراء|السيد|السيدة|الملك|الأمير|الأميرة|الشيخ|الشيخة"
              "|السلطان|العقيد|اللواء|الفريق|المشير|الدكتور|الدكتورة")
_AR_NAME = "[ء-يً-ْ]+"
_AR_MARKER = re.compile(
    rf"^[ \t]*(?P<who>(?:{_AR_TITLES})(?:[ \t]+{_AR_NAME}){{1,5}}|{_AR_ROLES})[ \t]*{_NOTES}[:：]", re.M)

# "Mr. President:" is a speaker addressing someone, not a speaker's label.
_NOT_NAMES = {"President", "Chairman", "Chairperson", "Speaker", "Secretary-General", "Minister",
              "Assembly", "الرئيس", "الرئيسة"}
_CHAIR = re.compile(r"^(?:The (?:Acting |Temporary )?President|The Chair(?:man|person)?|The Speaker"
                    "|الرئيس(?:ة)?(?: بالنيابة| المؤقت)?)$")
_ROLE = re.compile(r"^(?:The |الرئيس(?:ة)?(?: بالنيابة| المؤقت)?$)")
_SPOKE_IN = re.compile(r"spoke\s+in\s+([^\W\d_]+)|(?:تكلم|تكلمت)\s+(?:باللغة\s+)?(\S+?)\s*[;)؛]?\s*$", re.I)
_ADDRESS = re.compile(r"Address by\s+(.{5,250}?)(?=\s*\n\s*(?:The (?:Acting )?President|Mr\.|Mrs\.|Ms\.|His |Her )|\n\s*\n)", re.S)
_HONORIFIC = re.compile(r"^(?:Mr\.|Mrs\.|Ms\.)\s*")

_MIN_SPEECH_WORDS = 50    # shorter turns are remarks, not speeches
_MIN_CHAIR_SPEECH_WORDS = 300  # a chair's opening statement, not "the floor is yours"
CHAIR_REMARKS = "chair-remarks"


def _clean(s: str) -> str:
    return " ".join(s.split())


def _spoke_in(notes: str) -> str | None:
    m = _SPOKE_IN.search(_clean(notes).replace("(", " ").replace(")", " ").strip())
    return (m.group(1) or m.group(2)) if m else None


def _identity(who: str, text: str, pos: int) -> tuple[str, str | None]:
    """(name, title), from the nearest "Address by Mr. X, President of Y" before the turn."""
    words = {w for w in who.split()[1:] if len(w) > 2}
    for m in reversed(list(_ADDRESS.finditer(text, max(0, pos - 2000), pos))):
        name, _, title = _clean(m.group(1)).partition(", ")
        if words & set(name.split()):
            return _HONORIFIC.sub("", name), title or None
    return who, None


def split_speeches(text: str) -> list[dict]:
    """One {id, speaker, title, spoke_in, kind, words, text} per speaker, in order of
    first appearance, with the chair's short remarks last. Empty unless the document
    really has several speakers."""
    marker = _EN_MARKER if len(_EN_MARKER.findall(text)) >= len(_AR_MARKER.findall(text)) else _AR_MARKER
    turns = [m for m in marker.finditer(text)
             if _clean(m["who"]).split()[-1] not in _NOT_NAMES or _ROLE.match(_clean(m["who"]))]
    speakers: dict[str, dict] = {}
    remarks: list[str] = []
    for m, nxt in zip(turns, turns[1:] + [None]):
        who = _clean(m["who"])
        body = text[m.end():nxt.start() if nxt else len(text)].strip()
        words = len(body.split())
        chair = bool(_CHAIR.match(who))
        if words < (_MIN_CHAIR_SPEECH_WORDS if chair else _MIN_SPEECH_WORDS):
            remarks.append(body)
            continue
        entry = speakers.get(who)
        if entry is None:
            name, title = _identity(who, text, m.start())
            entry = speakers[who] = {"id": f"s{len(speakers) + 1}", "speaker": name, "title": title,
                                     "spoke_in": _spoke_in(m["notes"]), "kind": "speech", "parts": []}
        entry["parts"].append(body)
    if len(speakers) < 2:
        return []
    out = []
    for entry in speakers.values():
        body = "\n\n".join(entry.pop("parts"))
        out.append({**entry, "words": len(body.split()), "text": body})
    if remarks:
        body = "\n\n".join(remarks)
        out.append({"id": CHAIR_REMARKS, "speaker": "", "title": None, "spoke_in": None,
                    "kind": "chair", "words": len(body.split()), "text": body})
    return out
