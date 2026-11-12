"""Build the downloadable guide PDFs from docs/guide/*.html.

    python tools/build_guide_pdf.py

Prints each HTML handbook to frontend/public/guide/ with a headless Chromium browser
(Microsoft Edge or Google Chrome), which lays out Arabic text correctly. Re-run it after
editing docs/guide/cortex-guide-en.html or cortex-guide-ar.html, and commit the PDFs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "guide"
OUT = ROOT / "frontend" / "public" / "guide"
GUIDES = {"cortex-guide-en.html": "Cortex-Guide-EN.pdf", "cortex-guide-ar.html": "Cortex-Guide-AR.pdf"}

_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def browser() -> str:
    for name in ("msedge", "google-chrome", "chromium", "chrome"):
        if found := shutil.which(name):
            return found
    for path in _CANDIDATES:
        if os.path.exists(path):
            return path
    sys.exit("No Edge or Chrome found: install one, or print the HTML to PDF by hand.")


def main() -> None:
    exe = browser()
    OUT.mkdir(parents=True, exist_ok=True)
    for src, pdf in GUIDES.items():
        target = OUT / pdf
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={target}", (SRC / src).as_uri()],
                       check=True, timeout=180, capture_output=True)
        print(f"{target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
