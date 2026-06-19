# PoliticalPredictor — scoring engine

Scores a political leader's text on two at-a-distance content-analysis
methodologies and returns structured, JSON-friendly results:

- **LTA** — Hermann's *Leadership Trait Analysis* (7 traits: BACE, PWR, CC, SC, TASK, DIS, IGB)
- **VICS** — Walker's *Verbs In Context System* (operational-code indices P-1…P-5, I-1…I-5, Summary)

## Layout

| File | Role |
|---|---|
| `lexicons/lta/*.txt` | Curated LTA word lists (from `list of words LTA.pdf`) — the current dictionaries |
| `dictionaries.py` | Loads the curated lexicons (and legacy `.rtf` lists for comparison) |
| `nlp.py` | spaCy lemmatization + POS; lemma/surface matching |
| `text_utils.py` | Regex tokenizing + phrase-aware surface matching (used by VICS) |
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
- **LTA matching is lemma-based** (spaCy): "possibilities" matches "possibility".
- **Phrase-aware** for VICS: the originals counted single tokens via `Counter`,
  silently missing multi-word entries (e.g. "on the other hand"). Fixed here.
- **Divide-by-zero guarded** throughout (several originals crash on empty categories).

## Matching config

POS filtering (verbs-only for BACE/PWR, nouns for TASK) is implemented and
Hermann-faithful but OFF by default — on current data it cuts recall more than it
helps. Toggle for experiments: `import predictor.lta as lta; lta.USE_POS = True`.

## The real bottleneck: validation data, not the matcher

`validate_mock()` measures ordering concordance vs the labelled profiles. Across
matching strategies it lands ~60–68% overall, and the differences are within
noise — because the synthetic prose speeches (P1–P5) embody traits *semantically*
but barely use dictionary words. The speech labelled **PWR 95%** contains **one**
literal power word. So the dictionary scorer:

- works well on **keyword-dense** text (Kael/Marina score cleanly), and
- under-signals on **natural prose**, where meaning != vocabulary.

| Trait | concordance (lemma, no POS) | note |
|---|---|---|
| DIS | 88% | strong |
| SC, IGB | 71–75% | good |
| CC | 53% | lemma fixed the morphology gap (was 40%) |
| BACE, TASK | 50–55% | sparse signal on prose |
| PWR | 40% | very sparse; "armed forces" noun inflates low-PWR speeches |

**For "deepening the science":**
1. Keep the dictionary scorer as a fast, explainable baseline.
2. For natural speech, add a **semantic** scorer (embeddings or an LLM/Claude
   classifier reading meaning, not keywords), validated against **expert-coded
   real speeches**, not synthetic ones.
3. Bands are **relative** to the norming corpus — for absolute High/Low, norm
   against a broad, neutral leader set, not just war speeches.

Minor data gaps: `VICS .../Q4bI_txt/words.txt` is absent (I-4b is deeds-only);
the legacy `S.C.rtf` omitted "my" (the curated `SC.txt` includes it).
