"""Share the context-check examples between computers through the git repository.

Each computer keeps its examples in its own database (SQLite, or Postgres when
DATABASE_URL is set). This module mirrors them to `shared/context_labels.jsonl`,
a committed file with one example per line, sorted, so git can merge two people's
additions:

- `export(store)` runs after every save and rewrites the file from the database;
- `pull_in(store)` reads the file into the database (an example only replaces the
  one already there when it was saved later). It runs when the server starts and
  before every context check, so a `git pull` takes effect without a restart.

Lines that aren't valid JSON (for example git conflict markers) are skipped and
counted, so one bad merge can't break the context check.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

SYNC_FILE = Path(__file__).resolve().parent.parent / "shared" / "context_labels.jsonl"
_lock = threading.Lock()
_seen_mtime: float | None = None
last_report: dict = {"imported": 0, "skipped_lines": 0}


def _stamp(rec: dict) -> str:
    return rec.get("updated") or rec.get("saved") or ""


def _read(path: Path) -> tuple[list[dict], int]:
    recs, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(rec, dict) and rec.get("id") and rec.get("text"):
            recs.append(rec)
        else:
            bad += 1
    return recs, bad


def pull_in(store, force: bool = False) -> dict:
    """Bring examples from the shared file into the database. Cheap when the file
    hasn't changed since the last look."""
    global _seen_mtime
    if not SYNC_FILE.exists():
        return last_report
    with _lock:
        mtime = SYNC_FILE.stat().st_mtime
        if not force and mtime == _seen_mtime:
            return last_report
        recs, bad = _read(SYNC_FILE)
        have = {r["id"]: r for r in store.labels()}
        newer = [r for r in recs if r["id"] not in have or _stamp(r) > _stamp(have[r["id"]])]
        if newer:
            store.save_labels(newer)
        _seen_mtime = mtime
        last_report.update(imported=len(newer), skipped_lines=bad)
        return last_report


def export(store) -> int:
    """Rewrite the shared file from the database: one example per line, sorted by id."""
    global _seen_mtime
    with _lock:
        rows = sorted(store.labels(), key=lambda r: r["id"])
        body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not SYNC_FILE.exists() or SYNC_FILE.read_text(encoding="utf-8") != body:
            SYNC_FILE.write_text(body, encoding="utf-8")
        _seen_mtime = SYNC_FILE.stat().st_mtime
        return len(rows)
