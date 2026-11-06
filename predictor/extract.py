"""Pull the speech text out of an uploaded file (.txt, .pdf, .docx).

Errors are short codes the front-end turns into a message in the user's language.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections import Counter
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_BYTES = 50 * 1024 * 1024
_MAX_DOCX_XML = 50 * 1024 * 1024  # a small .docx can unzip into something enormous
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_LOOKALIKES = str.maketrans({"ھ": "ه", "ہ": "ه", "ە": "ه",
                             "ی": "ي", "ک": "ك"})


class ExtractError(ValueError):
    """`code` is one of: file-type, file-too-big, file-empty, file-unreadable,
    pdf-locked, pdf-no-text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _from_txt(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Arabic text saved by older Windows programs.
        return data.decode("cp1256", errors="replace")


def _strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove short lines repeated across many pages: running headers and page footers."""
    def shape(line: str) -> str:
        return re.sub(r"\d", "#", " ".join(line.split()))

    seen = Counter(s for page in pages for s in {shape(l) for l in page.splitlines()} if 0 < len(s) <= 40)
    repeated = {s for s, n in seen.items() if n >= max(3, 0.3 * len(pages))}
    return ["\n".join(l for l in page.splitlines() if shape(l) not in repeated) for page in pages]


def _from_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractError("pdf-locked")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ExtractError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ExtractError("file-unreadable") from exc
    pages = _strip_page_furniture(pages)
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise ExtractError("pdf-no-text")  # a scan: pictures of pages, no text in it
    # PDFs often store Arabic as presentation forms and "fi" as one ligature glyph,
    # and fonts draw some letters with Persian/Urdu look-alikes, which would split words.
    return unicodedata.normalize("NFKC", text).translate(_LOOKALIKES)


def _from_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if zf.getinfo("word/document.xml").file_size > _MAX_DOCX_XML:
                raise ExtractError("file-too-big")
            root = ElementTree.fromstring(zf.read("word/document.xml"))
    except ExtractError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ExtractError("file-unreadable") from exc
    paragraphs = []
    for para in root.iter(f"{_WORD_NS}p"):
        parts = []
        for node in para.iter():
            if node.tag == f"{_WORD_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{_WORD_NS}tab":
                parts.append("\t")
            elif node.tag == f"{_WORD_NS}br":
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n\n".join(p for p in paragraphs if p.strip())


_READERS = {"txt": _from_txt, "pdf": _from_pdf, "docx": _from_docx}


def extract_text(filename: str, data: bytes) -> str:
    """The text of an uploaded file; raises ExtractError if there is none to use."""
    reader = _READERS.get(filename.rsplit(".", 1)[-1].lower())
    if reader is None:
        raise ExtractError("file-type")
    if len(data) > MAX_BYTES:
        raise ExtractError("file-too-big")
    text = reader(data).strip()
    if not text:
        raise ExtractError("file-empty")
    return text
