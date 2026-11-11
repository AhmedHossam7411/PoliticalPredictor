# Baseline speeches

Put a real speech by a built-in stakeholder here as `<id>.txt` (for example
`sisi.txt` or `mbs.txt`; the ids are in `predictor/stakeholders.py`), then run

    python -m predictor.calibrate_baselines

to distil it into that person's decision profile. Use real, sourced speeches
only: the AI reasons from them and may quote them.
