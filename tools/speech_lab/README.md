# Speech Lab

A test bench for the predictor's accuracy. You set each of Hermann's seven LTA
traits on a slider (0–100, 50 = an average world leader), the AI writes a
speech at those levels, and both of the predictor's scorers rate it:

- **Dictionary scorer:** the word lists. Its raw value becomes a percentile
  against the predictor's reference speeches.
- **AI scorer:** the LLM trait reading.

For each trait the page shows target vs measured, and whether the
High/Moderate/Low band matches. Highlights switch between the words the
**scorer counted** and the phrases the **AI intended** as trait signals.
Every run is logged to `results/runs.jsonl`; **Download CSV** exports them.

It's a separate tool: it imports `predictor/` but changes nothing in it.
Delete this folder to remove it.

## Run

From the repo root, with the local AI (Karnak) running, as for the predictor:

    python -m uvicorn tools.speech_lab.server:app --port 8100

Then open http://127.0.0.1:8100.

You can also click **Edit text**, then paste or change any speech and
re-score it against the current sliders.

## Reading the results

- **CC, SC, Task focus:** two word lists compete, so a target above 50 means the
  first list should win (High, or Problem-solving for Task), below 50 the second.
- **Other bands:** Hermann's ±1 SD rule. A target above 84 counts as High, below 16
  as Low. The dictionary's bands use the same cut-offs, against the reference
  speeches (English or Arabic).
- **Percentiles are approximate:** they assume a normal spread over a small
  reference set.
- **The AI score is circular:** the same family of model writes the speech and
  scores it, so its agreement is flattering. The dictionary scorer never sees
  how the speech was made and is the more independent check. The generator is
  not shown the word lists.
- **Language:** VICS is English-only and isn't part of this test. Arabic
  speeches are scored against the Arabic reference set; check the detected
  dialect in the speech header against what you asked for.
