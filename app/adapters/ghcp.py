"""GHCP adapter - reads GitHub Copilot session-store.db (best-effort schema).

NOTE: Real GHCP DB schema not available at implementation time. This adapter
encodes a best-effort assumption documented in plan.md. schema_check() will
loudly fail if reality differs so we know to update.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterator, Optional

from app.adapters.base import Adapter, SchemaMismatchError
from app.models import UnifiedSession, truncate


GHCP_SESSION_COLS = {'id', 'title', 'created_at', 'updated_at', 'cwd', 'summary'}
GHCP_MESSAGE_COLS = {'id', 'session_id', 'role', 'content', 'created_at'}


def _epoch_to_iso(ts) -> str:
    if ts is None:
        return ''
    try:
        # Treat very large numbers as ms; small as seconds.
        v = float(ts)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ''


class GHCPAdapter(Adapter):
    source = 'ghcp'

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def schema_check(self) -> None:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f'GHCP db not found: {self.db_path}')
        try:
            conn = self._connect()
        except sqlite3.OperationalError as e:
            raise SchemaMismatchError(f'Cannot open GHCP db: {e}') from e
        try:
            cur = conn.cursor()
            for table, required in (('sessions', GHCP_SESSION_COLS),
                                     ('messages', GHCP_MESSAGE_COLS)):
                cur.execute(f"PRAGMA table_info({table})")
                cols = {r[1] for r in cur.fetchall()}
                if not cols:
                    raise SchemaMismatchError(
                        f'GHCP schema may have changed; update adapter '
                        f'(missing table: {table})')
                missing = required - cols
                if missing:
                    raise SchemaMismatchError(
                        f'GHCP schema may have changed; update adapter '
                        f'(table {table} missing columns: {missing})')
        finally:
            conn.close()

    def list_sessions(self) -> Iterator[UnifiedSession]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title, created_at, updated_at, cwd, summary "
                "FROM sessions ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
            for row in rows:
                sid = row['id']
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT content FROM messages WHERE session_id=? AND role='user' "
                    "ORDER BY created_at LIMIT 1", (sid,)
                )
                first = cur2.fetchone()
                first_user = first['content'] if first else ''
                cur2.execute(
                    "SELECT content FROM messages WHERE session_id=? "
                    "ORDER BY created_at LIMIT 10", (sid,)
                )
                body_parts = [r['content'] or '' for r in cur2.fetchall()]
                body = '\n\n'.join(body_parts)
                cur2.execute(
                    "SELECT COUNT(*) AS c FROM messages WHERE session_id=?", (sid,)
                )
                turns = cur2.fetchone()['c']
                title = row['title'] or truncate(first_user, 80) or f'(untitled {sid})'
                yield UnifiedSession(
                    id=f'ghcp:{sid}',
                    source=self.source,
                    title=title,
                    created_at=_epoch_to_iso(row['created_at']),
                    updated_at=_epoch_to_iso(row['updated_at']),
                    turns=turns,
                    model=None,
                    cwd=row['cwd'],
                    first_user_msg=first_user or '',
                    body=body,
                )
        finally:
            conn.close()

    def get_session_messages(self, session_id: str) -> list[dict]:
        sid = session_id.split(':', 1)[1] if session_id.startswith('ghcp:') else session_id
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id=? ORDER BY created_at", (sid,)
            )
            return [
                {
                    'role': r['role'],
                    'content': r['content'],
                    'timestamp': _epoch_to_iso(r['created_at']),
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()
