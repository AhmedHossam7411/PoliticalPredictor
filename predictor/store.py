"""Storage for user-added stakeholders.

Backend is chosen by environment, so the same code runs locally and hosted:
  * DATABASE_URL set  -> Postgres (persists across restarts; required for cloud
    hosts, whose filesystems are ephemeral).
  * otherwise         -> a local JSON file (custom_stakeholders.json), for dev.

A record is the whole custom stakeholder: the bio fields plus its baseline
`speech` and distilled `profile`. Built-in stakeholders and their bundled
profiles/speeches live in code and committed files, not here.

The `owner` column is written now (defaulting to one shared workspace) so the
schema is multi-tenant-ready; per-entity isolation switches on in Phase 2 once
real accounts exist.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_JSON_PATH = Path(__file__).resolve().parent / "custom_stakeholders.json"


class JsonStore:
    """Dev store: a single JSON file on disk."""

    def __init__(self, path: Path = _JSON_PATH):
        self.path = path

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


def get_store():
    """JsonStore locally, PgStore when DATABASE_URL is present."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return PgStore(url, owner=os.environ.get("WORKSPACE_OWNER", "default"))
    return JsonStore()
