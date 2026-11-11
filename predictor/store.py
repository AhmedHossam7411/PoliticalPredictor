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

_JSON_PATH = Path(__file__).resolve().parent / "custom_stakeholders.json"
_HIDDEN_PATH = Path(__file__).resolve().parent / "hidden_stakeholders.json"
_SPEECHES_PATH = Path(__file__).resolve().parent / "stakeholder_speeches.json"


class JsonStore:
    """Dev store: a single JSON file on disk."""

    def __init__(self, path: Path = _JSON_PATH, hidden_path: Path = _HIDDEN_PATH,
                 speeches_path: Path = _SPEECHES_PATH):
        self.path = path
        self.hidden_path = hidden_path
        self.speeches_path = speeches_path

    def list(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def add(self, record: dict) -> None:
        data = self.list()
        data.append(record)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, sid: str) -> bool:
        data = self.list()
        kept = [r for r in data if r.get("id") != sid]
        if len(kept) == len(data):
            return False
        self.path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def hidden(self) -> set[str]:
        try:
            return set(json.loads(self.hidden_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return set()

    def set_hidden(self, sid: str, hidden: bool) -> None:
        ids = self.hidden()
        ids = ids | {sid} if hidden else ids - {sid}
        self.hidden_path.write_text(json.dumps(sorted(ids)), encoding="utf-8")

    # Speeches saved for a stakeholder (any, built-in or added): {sid: [record, ...]}
    def _all_speeches(self) -> dict:
        try:
            return json.loads(self.speeches_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def speeches(self, sid: str) -> list[dict]:
        return self._all_speeches().get(sid, [])

    def add_speech(self, sid: str, record: dict) -> None:
        data = self._all_speeches()
        data.setdefault(sid, []).append(record)
        self.speeches_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete_speech(self, sid: str, speech_id: str) -> bool:
        data = self._all_speeches()
        kept = [r for r in data.get(sid, []) if r.get("id") != speech_id]
        if len(kept) == len(data.get(sid, [])):
            return False
        data[sid] = kept
        self.speeches_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


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
