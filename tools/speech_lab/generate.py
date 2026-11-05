"""Write a speech with chosen LTA trait levels, via the predictor's LLM client.

The model is told the target level (0-100) of each of Hermann's seven traits
and asked for a ~600-word speech plus the exact phrases it used to express each
trait ("intended markers"). It is NOT shown the scorer's word lists, so the
dictionary scorer is tested on how a leader might really talk, not on text
written to game it.
"""
from __future__ import annotations

import json
import re

from predictor.llm import chat_json

TRAITS = ("BACE", "PWR", "CC", "SC", "TASK", "DIS", "IGB")

TRAIT_DEFS = {
    "BACE": ("Belief in ability to control events",
             "High = takes charge, initiates, shapes outcomes. "
             "Low = reactive, waits, says events are beyond control."),
    "PWR": ("Need for power",
            "High = dominates, asserts authority, outmaneuvers, controls others. "
            "Low = collaborative, shares influence, defers to partners."),
    "CC": ("Conceptual complexity",
           "High = nuance, several perspectives, conditionals, uncertainty, trade-offs. "
           "Low = absolutes, black-and-white certainty, one view only."),
    "SC": ("Self-confidence",
           "High = self-assured, speaks with personal authority ('I know', 'I decided'). "
           "Low = self-doubt, hedges about self, leans on others' judgment."),
    "TASK": ("Task focus (vs. relationship focus)",
             "High = problems, goals, plans, getting things done. "
             "Low = people, feelings, morale, unity, caring for the group."),
    "DIS": ("Distrust of others",
            "High = suspicion, threats, enemies, betrayal, hidden agendas. "
            "Low = trusting, sees others as partners acting in good faith."),
    "IGB": ("In-group bias",
            "High = us-vs-them, strong national pride, outsiders as threats. "
            "Low = inclusive, shared humanity, little nationalism."),
}

LANGUAGES = {
    "en": "English",
    "msa": "Modern Standard Arabic (fusha), as in a formal televised address",
    "egyptian": "Egyptian colloquial Arabic (ammiya) throughout, as in a popular "
                "address by an Egyptian leader -- not Modern Standard Arabic",
}


def level_words(v: int) -> str:
    if v <= 15:
        return "very low"
    if v <= 35:
        return "low"
    if v < 65:
        return "average"
    if v < 85:
        return "high"
    return "very high"


_SYSTEM = """You write realistic political speeches for testing a Leadership \
Trait Analysis (Margaret G. Hermann) scoring tool. You will be given a target \
level (0-100, where 50 is average for a world leader) for each of the seven LTA \
traits. Write a speech whose psychology matches EVERY target: the stronger a \
trait's level departs from 50, the more clearly and often the speech should \
show it (high levels through the high-pole behaviour, low levels through the \
low-pole behaviour). Average levels should read as balanced and unremarkable.

Rules:
- Write a natural speech a real leader could give. Never name the traits or \
the scoring method, and do not stuff keywords.
- Length: {words} words in total. Write {paras} paragraphs of about {per} \
words each; do not stop early.
- Language: {language}.
- After writing, list the phrases you used to express each trait: for each \
trait, 3-6 short phrases (1-8 words) copied EXACTLY, character for character, \
from the speech, each with the pole it expresses ("high" or "low").

Respond ONLY with JSON of this shape:
{{"title": "<short title>",
  "speech": "<the full speech; paragraphs separated by \\n\\n>",
  "markers": [{{"trait": "PWR", "pole": "high", "phrase": "<exact substring>"}}, ...]}}"""


def _targets_block(targets: dict[str, int]) -> str:
    lines = []
    for t in TRAITS:
        name, desc = TRAIT_DEFS[t]
        v = int(targets[t])
        lines.append(f"- {t} ({name}): {v}/100 = {level_words(v)}. {desc}")
    return "\n".join(lines)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def locate(speech: str, phrase: str) -> tuple[int, int] | None:
    """Character span of a marker phrase in the speech (exact, then case-insensitive)."""
    i = speech.find(phrase)
    if i < 0:
        i = speech.lower().find(phrase.lower())
    return (i, i + len(phrase)) if i >= 0 else None


def generate(targets: dict[str, int], language: str = "en", topic: str = "",
             words: int = 600) -> dict:
    """Return {title, speech, words, model, intended: [spans], markers_found/total}."""
    paras = max(3, round(words / 100))
    system = _SYSTEM.format(words=words, paras=paras, per=round(words / paras),
                            language=LANGUAGES[language])
    user = "Target trait levels:\n" + _targets_block(targets)
    user += f"\n\nTopic / occasion: {topic.strip() or 'a national address on a current crisis'}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    # Low reasoning effort: gpt-oss's hidden reasoning otherwise eats most of
    # Groq's free-tier tokens-per-minute budget.
    data, model = chat_json(messages, temperature=0.8, max_wait=60.0, reasoning_effort="low")
    # Models undershoot long targets (Arabic especially): one lengthening pass.
    # It resends the speech, so on a tight rate limit it may fail; then the
    # shorter speech is kept (its word count is shown).
    n = word_count(str(data.get("speech", "")))
    if n < 0.85 * words:
        messages += [{"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                     {"role": "user", "content":
                      f"The speech has only {n} words; it must have about {words}. "
                      "Rewrite it at full length with the same trait levels, and "
                      "redo the markers for the new text. Same JSON shape."}]
        try:
            longer, m = chat_json(messages, temperature=0.8, max_wait=60.0,
                                  reasoning_effort="low")
            if word_count(str(longer.get("speech", ""))) > n:
                data, model = longer, m
        except Exception:  # noqa: BLE001 -- keep the first speech
            pass
    speech = str(data.get("speech", "")).strip()
    intended, total = [], 0
    for m in data.get("markers") or []:
        if not isinstance(m, dict) or m.get("trait") not in TRAITS:
            continue
        total += 1
        span = locate(speech, str(m.get("phrase", "")).strip())
        if span and span[1] > span[0]:
            pole = "low" if m.get("pole") == "low" else "high"
            intended.append({"start": span[0], "end": span[1],
                             "labels": [f"{m['trait']}:{pole}"]})
    return {"title": str(data.get("title", "")), "speech": speech,
            "words": word_count(speech), "model": model,
            "intended": intended, "markers_found": len(intended), "markers_total": total}
