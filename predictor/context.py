"""Context check: read each marked word inside its whole sentence.

The word scorer counts list words wherever they appear, so "she's in great shape"
counts "shape" as control of events, and "I built the greatest economy in the
history of the world" counts only "built" although the whole sentence shows
self-confidence. This module lists every sentence that has a marked word or names
a country/organization, and applies decisions about them:

- ignore: a marked word that doesn't carry its trait here is not counted;
- count:  a word the scorer left out (someone else acts) is counted after all;
- confirm: a person ticked that the word scorer was right about this word (no change
          to the score; it marks the example as checked for training);
- add:    the sentence as a whole, or a part of it (`start`/`end`/`text`), shows a
          trait, counted as one more hit;
- tones:  the speaker's attitude to a country/organization in that sentence.

The decisions come from Karnak (`start_ai`, run in the background, sentence groups
at a time) or from a person clicking in the review panel, or both. They are keyed
by hit number and sentence number, which are fixed for a given text, so they can be
saved with a speech and applied again. Reviewed sentences can be stored as labelled
examples; every later context check uses them: a sentence saved before gets its saved
decisions back, and Karnak is shown the most similar saved sentences as examples.
"""
from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
import uuid

from . import arabic, entities
from .highlight import scorer_spans
from .score import analyze, band_lta, recount

# Short codes the AI and the panel use for a word list (pole included).
CODE_OF = {"BACE:high": "BACE", "PWR:high": "PWR", "SC:high": "SC+", "SC:low": "SC-",
           "CC:high": "CC+", "CC:low": "CC-", "TASK:high": "TASK", "TASK:low": "REL",
           "DIS:high": "DIS", "IGB:high": "IGB"}
LABEL_OF = {v: k for k, v in CODE_OF.items()}
TONES = ("positive", "negative", "neutral")
_SKIPPED = ("other", "denied")


# --------------------------------------------------------------------------- #
# Sentences
# --------------------------------------------------------------------------- #
_AR_END = re.compile(r"[.!?؟…]+[\"”’»)]*\s+|\n\s*\n|\n(?=\S)")


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) character offsets of each sentence, in order."""
    if arabic.is_arabic(text):
        out, start = [], 0
        for m in _AR_END.finditer(text):
            if text[start:m.end()].strip():
                out.append((start, m.end()))
            start = m.end()
        if text[start:].strip():
            out.append((start, len(text)))
        return out or [(0, len(text))]
    from .nlp import parsed
    out = []
    for s in parsed(text).sents:
        # spaCy keeps a line break inside a sentence; split there too (titles, lists).
        start = s.start_char
        for m in re.finditer(r"\n\s*\n", text[s.start_char:s.end_char]):
            cut = s.start_char + m.end()
            if text[start:cut].strip():
                out.append((start, cut))
            start = cut
        if text[start:s.end_char].strip():
            out.append((start, s.end_char))
    return out or [(0, len(text))]


def _index_of(sents: list[tuple[int, int]], pos: int) -> int:
    lo, hi = 0, len(sents) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sents[mid][0] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


# --------------------------------------------------------------------------- #
# The review list
# --------------------------------------------------------------------------- #
def review(text: str) -> dict:
    """Every sentence with a marked word or a named country/organization.

    Each marked word is one `hit` (a word on two lists is one hit with two labels);
    `id` is its number in the text, used by decisions.
    """
    spans = scorer_spans(text)
    sents = sentences(text)
    words: dict[tuple[int, int], dict] = {}
    for sp in spans:
        w = words.setdefault((sp["start"], sp["end"]), {"start": sp["start"], "end": sp["end"],
                                                         "word": text[sp["start"]:sp["end"]], "labels": []})
        w["labels"] += sp["labels"]
    hits = sorted(words.values(), key=lambda w: w["start"])
    for i, h in enumerate(hits):
        h["id"] = i
        h["counted"] = any(l.split(":")[1] not in _SKIPPED for l in h["labels"])
    items: dict[int, dict] = {}

    def item(si: int) -> dict:
        if si not in items:
            s, e = sents[si]
            items[si] = {"i": si, "start": s, "end": e, "text": text[s:e], "hits": [], "entities": []}
        return items[si]

    for h in hits:
        item(_index_of(sents, h["start"]))["hits"].append(h)
    for m in entities.find(text):
        it = item(_index_of(sents, m["start"]))
        if not any(e["key"] == m["key"] for e in it["entities"]):
            it["entities"].append({**entities.info(m["key"]), "start": m["start"], "end": m["end"],
                                   "tone": entities.tone_of(it["text"])[0]})
    return {"sentences": [items[k] for k in sorted(items)], "hit_count": len(hits),
            "language": "ar" if arabic.is_arabic(text) else "en", "total_sentences": len(sents)}


def _clean(decisions: dict | None) -> dict:
    d = decisions or {}
    adds = []
    for a in d.get("add", []):
        if a.get("label") not in CODE_OF:
            continue
        add = {"sentence": int(a["sentence"]), "label": a["label"]}
        if a.get("start") is not None and a.get("end") is not None:
            add.update(start=int(a["start"]), end=int(a["end"]), text=str(a.get("text", ""))[:500])
        adds.append(add)
    return {"ignore": sorted({int(i) for i in d.get("ignore", [])}),
            "count": sorted({int(i) for i in d.get("count", [])}),
            "confirm": sorted({int(i) for i in d.get("confirm", [])}),
            "add": adds,
            "tones": [{"sentence": int(t["sentence"]), "entity": t["entity"], "tone": t["tone"],
                       "source": t.get("source", "person")} for t in d.get("tones", [])
                      if t.get("tone") in TONES and t.get("entity") in entities.ENTITIES]}


def deltas(text: str, decisions: dict | None) -> dict[str, int]:
    """How many hits each word list gains or loses under these decisions."""
    d = _clean(decisions)
    hits = {h["id"]: h for s in review(text)["sentences"] for h in s["hits"]}
    out: dict[str, int] = {}
    for i in d["ignore"]:
        for l in hits.get(i, {}).get("labels", []):
            if l.split(":")[1] not in _SKIPPED:
                out[l] = out.get(l, 0) - 1
    for i in d["count"]:
        h = hits.get(i)
        if h and i not in d["ignore"]:
            for l in h["labels"]:
                trait, role = l.split(":")
                if role in _SKIPPED:
                    out[f"{trait}:high"] = out.get(f"{trait}:high", 0) + 1
    for a in d["add"]:
        out[a["label"]] = out.get(a["label"], 0) + 1
    return out


def raw_lta(text: str, decisions: dict | None = None) -> dict:
    """The word scorer's raw counts for a text, with the decisions applied."""
    lta = copy.deepcopy(analyze(text)["lta"])
    return recount(lta, deltas(text, decisions)) if decisions else lta


def rescore(text: str, decisions: dict | None, norm: dict | None = None) -> dict:
    """The word-scorer result (as /analyze) after the context decisions."""
    result = analyze(text)
    result = {**result, "lta": raw_lta(text, decisions)}
    band_lta(result["lta"], norm)
    d = _clean(decisions)
    result["context"] = {"ignored": len(d["ignore"]), "counted": len(d["count"]),
                         "added": len(d["add"]), "toned": len(d["tones"]),
                         "confirmed": len(d["confirm"]),
                         "parts": sum(1 for a in d["add"] if "start" in a)}
    return result


def tone_map(decisions: dict | None) -> dict:
    return {(t["sentence"], t["entity"]): t for t in _clean(decisions)["tones"]}


# --------------------------------------------------------------------------- #
# Karnak's context check
# --------------------------------------------------------------------------- #
GROUP = 8          # sentences per AI call: short answers, steady progress
_MAX_CHARS = 600   # a sentence longer than this is cut for the AI

_PROMPT = """You check a word-counting tool used for Leadership Trait Analysis of \
political speeches. The tool marks single words from word lists and misses their \
context. Read each numbered sentence as a whole and decide:

1. "drop": marked words that do NOT carry their trait in this sentence. Example: \
"If the First Lady wasn't in great shape, she would have fallen" -- "shape" is about \
fitness, not shaping events; drop it. Small talk with no bearing on politics or \
foreign policy: drop its marked words.
2. "add": traits the WHOLE sentence clearly shows about the speaker, even if no word \
for it was marked. Example: "I built the greatest economy in the history of the \
world" shows strong self-confidence: add "SC+". Codes:
   BACE = the speaker believes they control events; PWR = seeks power or dominance \
over others; SC+ = self-confidence, boasting; SC- = self-doubt; CC+ = nuance, sees \
several sides; CC- = black-and-white certainty; TASK = focus on problems and goals; \
REL = focus on people and relationships; DIS = distrust or suspicion of others; \
IGB = us-versus-them, national pride.
   Only add a code the sentence really shows; most sentences need none.
3. "tone": for each name listed under "names", the speaker's attitude toward it in \
this sentence: "pos", "neg" or "neu".

List only sentences where you drop or add something, or that have names. Respond \
ONLY with JSON: {"s": [{"i": 3, "drop": ["shape"], "add": ["SC+"], "tone": {"UN": "neg"}}]}"""

_TONE_CODE = {"pos": "positive", "neg": "negative", "neu": "neutral",
              "positive": "positive", "negative": "negative", "neutral": "neutral"}


def _line(it: dict) -> str:
    text = " ".join(it["text"].split())[:_MAX_CHARS]
    marked = ", ".join(f"{h['word']}={'/'.join(CODE_OF[l] for l in h['labels'] if l in CODE_OF)}"
                       for h in it["hits"] if h["counted"])
    out = f"{it['i']}: {text}"
    if marked:
        out += f"\n   marked: {marked}"
    if it["entities"]:
        out += "\n   names: " + ", ".join(f"{e['key']} ({e['name']})" for e in it["entities"])
    return out


def _norm_word(w: str) -> str:
    return arabic.normalize(w).lower().strip(" .,'\"")


def _apply_answer(group: list[dict], answer: dict) -> dict:
    """Turn the AI's JSON into checked decisions for this group of sentences."""
    by_i = {it["i"]: it for it in group}
    out = {"ignore": [], "add": [], "tones": []}
    rows = answer.get("s") if isinstance(answer, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            it = by_i.get(int(row.get("i")))
        except (TypeError, ValueError):
            continue
        if not it:
            continue
        drops = {_norm_word(str(w)) for w in (row.get("drop") or []) if isinstance(w, (str, int))}
        kept_labels = set()
        for h in it["hits"]:
            if h["counted"] and _norm_word(h["word"]) in drops:
                out["ignore"].append(h["id"])
            elif h["counted"]:
                kept_labels.update(h["labels"])
        for code in row.get("add") or []:
            label = LABEL_OF.get(str(code).strip().upper().replace(" ", ""))
            # Already counted in this sentence: adding it again would count it twice.
            if label and label not in kept_labels:
                out["add"].append({"sentence": it["i"], "label": label})
                kept_labels.add(label)
        tone = row.get("tone") if isinstance(row.get("tone"), dict) else {}
        names = {e["key"] for e in it["entities"]}
        for key, val in tone.items():
            key = str(key).strip().upper()
            t = _TONE_CODE.get(str(val).strip().lower())
            if key in names and t:
                out["tones"].append({"sentence": it["i"], "entity": key, "tone": t, "source": "ai"})
    return out


# --------------------------------------------------------------------------- #
# Using the saved examples (predictor/context_labels.json, or the database)
# --------------------------------------------------------------------------- #
EXAMPLES_PER_GROUP = 4   # similar saved sentences shown to Karnak with each group
_WORD = re.compile(r"\w+")


def _words_of(text: str) -> set[str]:
    return {w for w in _WORD.findall(arabic.normalize(text).lower()) if len(w) > 2}


def _decided(rec: dict) -> bool:
    """A saved sentence carries a decision worth showing (not just 'nothing changed')."""
    return (any(w.get("confirmed") or not w.get("counted", True) for w in rec.get("words", []))
            or rec.get("added") or rec.get("parts") or rec.get("tones"))


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def saved_for(it: dict, labels_by_text: dict) -> dict | None:
    """The saved record of exactly this sentence, if there is one."""
    return labels_by_text.get(" ".join(it["text"].split()))


def reuse(it: dict, rec: dict) -> dict:
    """Decisions for a sentence saved earlier, mapped onto this text's hit numbers."""
    out = {"ignore": [], "count": [], "confirm": [], "add": [], "tones": []}
    saved = list(rec.get("words", []))
    for h in it["hits"]:
        # Same sentence, same marked words in the same order; match by word to be safe.
        j = next((k for k, w in enumerate(saved) if _norm_word(w.get("word", "")) == _norm_word(h["word"])), None)
        if j is None:
            continue
        w = saved.pop(j)
        if h["counted"] and not w.get("counted", True):
            out["ignore"].append(h["id"])
        elif not h["counted"] and w.get("counted"):
            out["count"].append(h["id"])
        if w.get("confirmed"):
            out["confirm"].append(h["id"])
    for label in rec.get("added", []):
        if label in CODE_OF:
            out["add"].append({"sentence": it["i"], "label": label})
    for part in rec.get("parts", []):
        at = it["text"].find(part.get("text", ""))
        if at >= 0 and part.get("label") in CODE_OF and part.get("text"):
            start = it["start"] + at
            out["add"].append({"sentence": it["i"], "label": part["label"], "start": start,
                               "end": start + len(part["text"]), "text": part["text"]})
    names = {e["key"] for e in it["entities"]}
    for key, tone in (rec.get("tones") or {}).items():
        if key in names and tone in TONES:
            out["tones"].append({"sentence": it["i"], "entity": key, "tone": tone, "source": "saved"})
    return out


def similar_examples(group: list[dict], labels: list[dict], k: int = EXAMPLES_PER_GROUP) -> list[dict]:
    """Saved sentences most like this group: sharing a marked word counts most, then
    shared words; same language first. Only sentences with a real decision."""
    if not labels:
        return []
    marked = {_norm_word(h["word"]) for it in group for h in it["hits"]}
    words = set().union(*(_words_of(it["text"]) for it in group))
    lang = "ar" if any(arabic.is_arabic(it["text"]) for it in group) else "en"
    texts = {" ".join(it["text"].split()) for it in group}
    scored = []
    for rec in labels:
        if not _decided(rec) or " ".join(rec.get("text", "").split()) in texts:
            continue
        shared_marked = len(marked & {_norm_word(w.get("word", "")) for w in rec.get("words", [])})
        rw = _words_of(rec.get("text", ""))
        overlap = len(words & rw) / (len(rw) or 1)
        score = 3 * shared_marked + overlap + (0.5 if rec.get("language") == lang else 0)
        if shared_marked or overlap >= 0.3:
            scored.append((score, rec))
    scored.sort(key=lambda x: -x[0])
    return [rec for _, rec in scored[:k]]


def _example_line(rec: dict) -> str:
    text = " ".join(rec.get("text", "").split())[:300]
    bits = []
    dropped = [w["word"] for w in rec.get("words", [])
               if not w.get("counted", True) and any(l.split(":")[1] not in _SKIPPED for l in w.get("labels", []))]
    right = [f"{w['word']}={'/'.join(CODE_OF[l] for l in w.get('labels', []) if l in CODE_OF)}"
             for w in rec.get("words", []) if w.get("confirmed") and w.get("counted", True)]
    if dropped:
        bits.append("drop: " + ", ".join(dropped))
    if right:
        bits.append("correct as marked: " + ", ".join(right))
    if rec.get("added"):
        bits.append("add: " + ", ".join(CODE_OF[l] for l in rec["added"] if l in CODE_OF))
    for part in rec.get("parts", []):
        if part.get("label") in CODE_OF:
            bits.append(f'the part "{part["text"][:120]}" shows {CODE_OF[part["label"]]}')
    if rec.get("tones"):
        bits.append("tone: " + ", ".join(f"{k}={'pos' if v == 'positive' else 'neg' if v == 'negative' else 'neu'}"
                                         for k, v in rec["tones"].items()))
    return f'- "{text}" -> ' + "; ".join(bits or ["nothing to change"])


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    return ("\n\nEarlier decisions by the analyst on similar sentences. Judge the new "
            "sentences the same way where the case is the same:\n"
            + "\n".join(_example_line(r) for r in examples))


_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def start_ai(text: str, labels: list[dict] | None = None) -> str:
    """Start the context check in the background; returns a job id to poll.

    `labels` are the saved examples: a sentence saved before gets its saved decisions
    straight away (no AI needed); for the others Karnak is shown the most similar
    saved sentences with each group.
    """
    items = review(text)["sentences"]
    groups = [items[i:i + GROUP] for i in range(0, len(items), GROUP)]
    job = {"id": uuid.uuid4().hex[:12], "status": "running", "done": 0, "total": len(groups),
           "decisions": {"ignore": [], "count": [], "confirm": [], "add": [], "tones": []},
           "reviewed": [], "reused": [], "examples": 0, "error": "",
           "started": time.time(), "cancel": False}
    with _JOBS_LOCK:
        # Keep the last few jobs only.
        for old in sorted(_JOBS, key=lambda k: _JOBS[k]["started"])[:-10]:
            _JOBS.pop(old, None)
        _JOBS[job["id"]] = job
    threading.Thread(target=_run, args=(job, groups, labels or []), daemon=True).start()
    return job["id"]


def _run(job: dict, groups: list[list[dict]], labels: list[dict]) -> None:
    from .llm import chat_json
    by_text = {" ".join(r.get("text", "").split()): r for r in labels}
    failures = 0
    for group in groups:
        if job["cancel"]:
            job["status"] = "cancelled"
            return
        # Sentences decided before: take the saved decisions, don't ask again.
        fresh = []
        for it in group:
            rec = saved_for(it, by_text)
            if rec:
                for k, v in reuse(it, rec).items():
                    job["decisions"][k] += v
                job["reused"].append(it["i"])
                job["reviewed"].append(it["i"])
            else:
                fresh.append(it)
        if fresh:
            examples = similar_examples(fresh, labels)
            job["examples"] += len(examples)
            try:
                answer, _ = chat_json([{"role": "system", "content": _PROMPT + _examples_block(examples)},
                                       {"role": "user", "content": "\n".join(_line(it) for it in fresh)}],
                                      temperature=0.1)
                got = _apply_answer(fresh, answer)
                for k in got:
                    job["decisions"][k] += got[k]
                job["reviewed"] += [it["i"] for it in fresh]
            except Exception as exc:  # one bad answer shouldn't stop the rest
                failures += 1
                job["error"] = f"{type(exc).__name__}: {exc}"[:300]
                if failures >= 3 and not job["reviewed"]:
                    job["status"] = "failed"
                    return
        job["done"] += 1
    job["status"] = "done"


def job_status(job_id: str) -> dict | None:
    job = _JOBS.get(job_id)
    if not job:
        return None
    return {k: v for k, v in job.items() if k != "cancel"}


def cancel(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if job:
        job["cancel"] = True
    return bool(job)


# --------------------------------------------------------------------------- #
# Labelled examples, for training a model later
# --------------------------------------------------------------------------- #
def label_records(text: str, decisions: dict, source: str) -> list[dict]:
    """One record per sentence: the sentence, its marked words (kept or not), the
    traits added for the whole sentence and the tones."""
    d = _clean(decisions)
    lang = "ar" if arabic.is_arabic(text) else "en"
    out = []
    for it in review(text)["sentences"]:
        rec = {"text": it["text"].strip(), "language": lang, "source": source,
               "words": [{"word": h["word"], "labels": h["labels"],
                          "counted": (h["counted"] and h["id"] not in d["ignore"])
                          or (h["id"] in d["count"] and h["id"] not in d["ignore"]),
                          "confirmed": h["id"] in d["confirm"]}
                         for h in it["hits"]],
               "added": [a["label"] for a in d["add"] if a["sentence"] == it["i"] and "start" not in a],
               "parts": [{"text": a["text"], "label": a["label"]} for a in d["add"]
                         if a["sentence"] == it["i"] and "start" in a],
               "tones": {t["entity"]: t["tone"] for t in d["tones"] if t["sentence"] == it["i"]},
               "saved": time.strftime("%Y-%m-%d"),
               # Decides which copy wins when two computers saved the same sentence.
               "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        rec["id"] = hashlib.sha1(rec["text"].encode("utf-8")).hexdigest()[:16]
        out.append(rec)
    return out
