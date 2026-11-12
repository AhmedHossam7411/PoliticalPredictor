"""Storage for user-added stakeholders.

Backend is chosen by environment, so the same code runs locally and hosted:
  * DATABASE_URL set  -> Postgres (persists across restarts; required for cloud
    hosts, whose filesystems are ephemeral).
  * otherwise         -> a local JSON file (custom_stakeholders.json), for dev.

A record is the whole custom stakeholder: the bio fields plus its baseline
`speech` and distilled `profile`. Built-in stakeholders and their bundled
profiles/speeches live in code and committed files, not here; the store only
remembers which built-ins were removed, so they can be restored.

The `owner` column is written now (defaulting to one shared workspace) so the
schema is multi-tenant-ready; per-entity isolation switches on in Phase 2 once
real accounts exist.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# The team's data lives in shared/, which is committed: a git push carries added
# stakeholders, removed ones, profile edits and saved speeches (with the statements
# saved from the analysis) to every other computer, like the context examples.
_SHARED = Path(__file__).resolve().parent.parent / "shared"
_JSON_PATH = _SHARED / "custom_stakeholders.json"
_HIDDEN_PATH = _SHARED / "hidden_stakeholders.json"
_SPEECHES_PATH = _SHARED / "stakeholder_speeches.json"
# Changes made in a stakeholder's profile ({sid: fields}); laid over the original.
_EDITS_PATH = _SHARED / "stakeholder_edits.json"


def _move_old_files() -> None:
    """Earlier versions kept these files in predictor/ (not committed): move them once."""
    old_dir = Path(__file__).resolve().parent
    for new in (_JSON_PATH, _HIDDEN_PATH, _SPEECHES_PATH, _EDITS_PATH):
        old = old_dir / new.name
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.replace(new)


_move_old_files()


class SharedFileConflict(RuntimeError):
    """A shared file can't be read (for example git left conflict markers in it)."""


def _read_json(path: Path, default, strict: bool = False):
    """A shared JSON file's contents. A missing file is empty. A broken one is reported:
    reading for display gives the default, but `strict` (before a write) refuses, so a
    bad git merge is never overwritten and lost."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        msg = (f"{path.name} in shared/ can't be read ({exc}). If git reported a merge "
               f"conflict in it, fix the file (keep both sides' entries), then try again.")
        if strict:
            raise SharedFileConflict(msg) from exc
        print(f"[store] {msg}")
        return default


def _write_json(path: Path, data) -> None:
    """Pretty-printed with sorted keys, so git shows and merges changes line by line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
# Sentences someone (or the AI) reviewed in the context check: examples Karnak follows.
# Kept in a SQLite database; the old JSON file is moved into it once.
_LABELS_DB = Path(__file__).resolve().parent / "cortex.db"
_LABELS_PATH = Path(__file__).resolve().parent / "context_labels.json"


class SqliteLabels:
    """The context-check examples in a local SQLite database (one row per sentence)."""

    def __init__(self, path: Path = _LABELS_DB, legacy: Path = _LABELS_PATH):
        import sqlite3
        self.path = path
        self._sqlite = sqlite3
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS context_labels (
                            id TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL DEFAULT '')""")
        if legacy.exists():
            try:
                old = json.loads(legacy.read_text(encoding="utf-8"))
                self.save_labels(list(old.values()) if isinstance(old, dict) else old)
                legacy.rename(legacy.with_suffix(".json.moved-to-db"))
            except (OSError, json.JSONDecodeError, AttributeError, KeyError):
                pass

    def _connect(self):
        return self._sqlite.connect(self.path, timeout=10)

    def labels(self) -> list[dict]:
        with self._connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM context_labels ORDER BY updated, id")]

    def save_labels(self, records: list[dict]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT INTO context_labels (id, data, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                [(r["id"], json.dumps(r, ensure_ascii=False), r.get("updated") or r.get("saved") or "")
                 for r in records])


class JsonStore:
    """Dev store: a single JSON file on disk."""

    def __init__(self, path: Path = _JSON_PATH, hidden_path: Path = _HIDDEN_PATH,
                 speeches_path: Path = _SPEECHES_PATH, labels_db: Path = _LABELS_DB):
        self.path = path
        self.hidden_path = hidden_path
        self.speeches_path = speeches_path
        # Only the real database takes in the old JSON file (not a test's temporary one).
        self._labels = SqliteLabels(labels_db, _LABELS_PATH if labels_db == _LABELS_DB else labels_db.with_suffix(".none"))

    def list(self, strict: bool = False) -> list[dict]:
        return _read_json(self.path, [], strict)

    def add(self, record: dict) -> None:
        data = self.list(strict=True)
        data.append(record)
        _write_json(self.path, data)

    def delete(self, sid: str) -> bool:
        data = self.list(strict=True)
        kept = [r for r in data if r.get("id") != sid]
        if len(kept) == len(data):
            return False
        _write_json(self.path, kept)
        return True

    def hidden(self, strict: bool = False) -> set[str]:
        return set(_read_json(self.hidden_path, [], strict))

    def set_hidden(self, sid: str, hidden: bool) -> None:
        ids = self.hidden(strict=True)
        ids = ids | {sid} if hidden else ids - {sid}
        _write_json(self.hidden_path, sorted(ids))

    # Speeches saved for a stakeholder (any, built-in or added): {sid: [record, ...]}
    def _all_speeches(self, strict: bool = False) -> dict:
        return _read_json(self.speeches_path, {}, strict)

    def speeches(self, sid: str) -> list[dict]:
        return self._all_speeches().get(sid, [])

    def add_speech(self, sid: str, record: dict) -> None:
        data = self._all_speeches(strict=True)
        data.setdefault(sid, []).append(record)
        _write_json(self.speeches_path, data)

    def delete_speech(self, sid: str, speech_id: str) -> bool:
        data = self._all_speeches(strict=True)
        kept = [r for r in data.get(sid, []) if r.get("id") != speech_id]
        if len(kept) == len(data.get(sid, [])):
            return False
        data[sid] = kept
        _write_json(self.speeches_path, data)
        return True

    # Profile edits: {sid: fields}. None removes the edit (back to the original).
    def edits(self, strict: bool = False) -> dict:
        return _read_json(_EDITS_PATH, {}, strict) if self.path == _JSON_PATH else {}

    def set_edit(self, sid: str, data: dict | None) -> None:
        if self.path != _JSON_PATH:  # tests with temporary files keep edits in memory only
            return
        all_edits = self.edits(strict=True)
        if data is None:
            all_edits.pop(sid, None)
        else:
            all_edits[sid] = data
        _write_json(_EDITS_PATH, all_edits)

    # Labelled sentences from the context check; a sentence saved again replaces itself.
    def labels(self) -> list[dict]:
        return self._labels.labels()

    def save_labels(self, records: list[dict]) -> None:
        self._labels.save_labels(records)


class PgStore:
    """Production store: one Postgres row per stakeholder (id, owner, data jsonb)."""

    def __init__(self, url: str, owner: str = "default"):
        self.url = url
        self.owner = owner
        self._ensure()

    def _connect(self):
        import psycopg  # lazy import: only needed when DATABASE_URL is set
        return psycopg.connect(self.url)

    def _ensure(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stakeholders (
                    id          text PRIMARY KEY,
                    owner       text NOT NULL DEFAULT 'default',
                    data        jsonb NOT NULL,
                    created_at  timestamptz NOT NULL DEFAULT now()
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hidden_stakeholders (
                    id     text NOT NULL,
                    owner  text NOT NULL DEFAULT 'default',
                    PRIMARY KEY (id, owner)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stakeholder_speeches (
                    id          text NOT NULL,
                    sid         text NOT NULL,
                    owner       text NOT NULL DEFAULT 'default',
                    data        jsonb NOT NULL,
                    created_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, owner)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stakeholder_edits (
                    id          text NOT NULL,
                    owner       text NOT NULL DEFAULT 'default',
                    data        jsonb NOT NULL,
                    PRIMARY KEY (id, owner)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS context_labels (
                    id          text NOT NULL,
                    owner       text NOT NULL DEFAULT 'default',
                    data        jsonb NOT NULL,
                    updated_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, owner)
                )"""
            )
            conn.commit()

    def list(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM stakeholders WHERE owner = %s ORDER BY created_at",
                (self.owner,),
            ).fetchall()
        return [r[0] for r in rows]

    def add(self, record: dict) -> None:
        from psycopg.types.json import Jsonb
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO stakeholders (id, owner, data) VALUES (%s, %s, %s)",
                (record["id"], self.owner, Jsonb(record)),
            )
            conn.commit()

    def delete(self, sid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM stakeholders WHERE id = %s AND owner = %s",
                (sid, self.owner),
            )
            conn.commit()
            return cur.rowcount > 0

    def hidden(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM hidden_stakeholders WHERE owner = %s", (self.owner,),
            ).fetchall()
        return {r[0] for r in rows}

    def speeches(self, sid: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM stakeholder_speeches WHERE sid = %s AND owner = %s ORDER BY created_at",
                (sid, self.owner)).fetchall()
        return [r[0] for r in rows]

    def add_speech(self, sid: str, record: dict) -> None:
        from psycopg.types.json import Jsonb
        with self._connect() as conn:
            conn.execute("INSERT INTO stakeholder_speeches (id, sid, owner, data) VALUES (%s, %s, %s, %s)",
                         (record["id"], sid, self.owner, Jsonb(record)))
            conn.commit()

    def delete_speech(self, sid: str, speech_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM stakeholder_speeches WHERE id = %s AND sid = %s AND owner = %s",
                               (speech_id, sid, self.owner))
            conn.commit()
            return cur.rowcount > 0

    def edits(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, data FROM stakeholder_edits WHERE owner = %s", (self.owner,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_edit(self, sid: str, data: dict | None) -> None:
        from psycopg.types.json import Jsonb
        with self._connect() as conn:
            if data is None:
                conn.execute("DELETE FROM stakeholder_edits WHERE id = %s AND owner = %s", (sid, self.owner))
            else:
                conn.execute("INSERT INTO stakeholder_edits (id, owner, data) VALUES (%s, %s, %s) "
                             "ON CONFLICT (id, owner) DO UPDATE SET data = EXCLUDED.data", (sid, self.owner, Jsonb(data)))
            conn.commit()

    def labels(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT data FROM context_labels WHERE owner = %s ORDER BY updated_at",
                                (self.owner,)).fetchall()
        return [r[0] for r in rows]

    def save_labels(self, records: list[dict]) -> None:
        from psycopg.types.json import Jsonb
        with self._connect() as conn:
            for r in records:
                conn.execute("INSERT INTO context_labels (id, owner, data) VALUES (%s, %s, %s) "
                             "ON CONFLICT (id, owner) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                             (r["id"], self.owner, Jsonb(r)))
            conn.commit()

    def set_hidden(self, sid: str, hidden: bool) -> None:
        sql = ("INSERT INTO hidden_stakeholders (id, owner) VALUES (%s, %s) ON CONFLICT DO NOTHING"
               if hidden else "DELETE FROM hidden_stakeholders WHERE id = %s AND owner = %s")
        with self._connect() as conn:
            conn.execute(sql, (sid, self.owner))
            conn.commit()


def get_store():
    """JsonStore locally, PgStore when DATABASE_URL is present."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return PgStore(url, owner=os.environ.get("WORKSPACE_OWNER", "default"))
    return JsonStore()
