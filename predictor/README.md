# PoliticalPredictor — scoring engine

Scores a political leader's text on two at-a-distance content-analysis
methodologies and returns structured, JSON-friendly results:

- **LTA** — Hermann's *Leadership Trait Analysis* (7 traits: BACE, PWR, CC, SC, TASK, DIS, IGB)
- **VICS** — Walker's *Verbs In Context System* (operational-code indices P-1…P-5, I-1…I-5, Summary)

## Layout

| File | Role |
|---|---|
| `dictionaries.py` | Loads LTA `.rtf` and VICS `.txt` word lists into sets; seeds the missing TASK list |
| `text_utils.py` | Tokenizing + **phrase-aware** matching (multi-word entries) |
| `lta.py` | 7-trait scorer (CC/TASK = ratios; others = density /1k tokens) |
| `vics.py` | All operational-code indices, consolidated from the 12 original scripts |
| `score.py` | Integrated report + norming (High/Mod/Low vs a corpus) + validation |
| `mock_speeches.py` | 5 labelled synthetic speeches used as norming corpus + test cases |
| `api.py` | FastAPI HTTP layer for the Angular front-end |

## Run

```bash
# Validate the scorer against the mock-speech profiles, print an example report
python -m predictor.score

# Score any text file (LTA bands are relative to the mock-speech corpus)
python -m predictor.score path/to/speech.txt

# Inspect loaded dictionaries / individual methodologies
python -m predictor.dictionaries
python -m predictor.vics
```

## HTTP API (for the Angular front-end)

```bash
pip install -r requirements.txt
uvicorn predictor.api:app --reload          # http://127.0.0.1:8000
# interactive docs at /docs
```

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | – | `{status}` |
| GET | `/meta` | – | trait/index names + default norming corpus |
| GET | `/mock-speeches` | – | the 5 labelled demo speeches |
| POST | `/analyze` | `{text, norming_corpus?}` | full LTA (with bands) + VICS |
| POST | `/analyze/batch` | `{texts[], norming_corpus?}` | list of analyses |

`norming_corpus` is optional — omit it to band LTA traits against the bundled
mock speeches, or pass your own comparison set. CORS is open (`*`) for dev;
tighten `allow_origins` to the Angular origin before deploying.

Angular call sketch:

```ts
this.http.post('http://127.0.0.1:8000/analyze', { text: speech })
  .subscribe(r => this.report = r);   // r.lta.traits.CC.band, r.vics['P-4'].value, ...
```

## Design notes

- **LTA bands are relative.** High/Moderate/Low is assigned vs a norming group
  (Hermann's >1 SD rule), defaulting to the five mock speeches — not absolute
  cutoffs. Swap the corpus via `build_norm(...)` for a different comparison set.
- **Phrase-aware matching.** The original VICS scripts counted single tokens via
  `Counter`, silently missing every multi-word list entry (e.g. "on the other
  hand"). This engine matches phrases, so values can differ slightly — more
  correctly — from the originals.
- **Divide-by-zero guarded** throughout (several originals crash on empty categories).

## Known limitations / TODO

These come from the *dictionaries*, not the engine, and show up in
`validate_mock()` (ordering concordance vs the labelled profiles):

| Trait | Concordance | Issue |
|---|---|---|
| IGB | 100% | but inflated by counting bare "we/us/our" pronouns as in-group bias (Hermann requires a favorable/strength modifier) |
| CC, SC, TASK | 71–88% | good |
| BACE | 57% | list is control *vocabulary*, but Hermann scores control via **verbs of action by the speaker** |
| PWR | 38% | forceful-verb list ("attack", "crush") rarely appears even in high-power prose |
| DIS | 38% | list is adjectives ("suspicious"); speeches express distrust via nouns/phrases ("acted against our interests") |

Two missing pieces in the source data:
- `VICS Code/.../Q4bI_txt/words.txt` is absent (only `deeds.txt` ships) → I-4b is deeds-only.
- `S.C.rtf` omits the pronoun "my" (the manual lists my/myself/I/me/mine).

**Next-step options:** (a) enrich the PWR/DIS/BACE dictionaries; (b) upgrade to
verb/POS-based scoring with spaCy for faithful BACE/PWR/DIS coding; (c) expose
`analyze()` behind a FastAPI endpoint for the Angular front-end.
