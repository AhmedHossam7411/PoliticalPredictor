"""Arabic versions of the labelled mock speeches (sample_speeches_ar/).

Each English mock speech has a Modern Standard Arabic (`_msa`) and an Egyptian
colloquial (`_egy`) rendering with the same content and tone, so they carry the
same LTA profile labels. They serve as the Arabic norming corpus (Arabic
densities are not comparable with English ones) and as paste-in samples.
"""
from __future__ import annotations

import os

from .dictionaries import ROOT
from .mock_speeches import MOCK_SPEECHES

SAMPLES_AR_DIR = os.path.join(ROOT, "sample_speeches_ar")
VARIANTS = {"msa": "Modern Standard", "egy": "Egyptian"}


def _load() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, spec in MOCK_SPEECHES.items():
        for suffix, label in VARIANTS.items():
            path = os.path.join(SAMPLES_AR_DIR, f"{name}_{suffix}.txt")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                out[f"{name}_{suffix}"] = {"profile": spec["profile"],
                                           "variant": label, "text": fh.read()}
    return out


MOCK_SPEECHES_AR: dict[str, dict] = _load()
