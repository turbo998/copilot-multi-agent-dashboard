"""Hermes adapter - reads from Hermes state.db (sqlite)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterator, Optional

from app.adapters.base import Adapter, SchemaMismatchError
from app.models import UnifiedSession, truncate


HERMES_SESSION_COLS = {'id', 'source', 'model', 'started_at', 'ended_at', 'message_count', 'title'}
HERMES_MESSAGE_COLS = {'id', 'session_id', 'role', 'content', 'timestamp'}


def _epoch_to_iso(ts: Optional[float]) -> str:
    if ts is None:
        return ''
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ''


class HermesAdapter(Adapter):
    source = 'hermes'

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def schema_check(self) -> None:
        try:
            conn = self._connect()
        except sqlite3.OperationalError as e:
            raise SchemaMismatchError(f'Cannot open Hermes db: {e}') from e
        try:
            cur = conn.cursor()
            for table, required in (('sessions', HERMES_SESSION_COLS),
                                     ('messages', HERMES_MESSAGE_COLS)):
                cur.execute(f"PRAGMA table_info({table})")
                cols = {r[1] for r in cur.fetchall()}
                if not cols:
                    raise SchemaMismatchError(f'Hermes table missing: {table}')
                missing = required - cols
                if missing:
                    raise SchemaMismatchError(
                        f'Hermes table {table} missing columns: {missing}')
        finally:
            conn.close()

    def list_sessions(self) -> Iterator[UnifiedSession]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, model, started_at, ended_at, message_count, title "
                "FROM sessions WHERE message_count > 0 ORDER BY started_at DESC"
            )
            rows = cur.fetchall()
            for row in rows:
                sid = row['id']
                # first user message
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT content FROM messages WHERE session_id=? AND role='user' "
                    "ORDER BY timestamp LIMIT 1", (sid,)
                )
                first = cur2.fetchone()
                first_user = first['content'] if first else ''
                # body: first ~10 messages
                cur2.execute(
                    "SELECT content FROM messages WHERE session_id=? "
                    "ORDER BY timestamp LIMIT 10", (sid,)
                )
                body = '\n\n'.join((r['content'] or '') for r in cur2.fetchall())
                title = row['title'] or truncate(first_user, 80) or f'(untitled {sid})'
                yield UnifiedSession(
                    id=f'hermes:{sid}',
                    source=self.source,
                    title=title,
                    created_at=_epoch_to_iso(row['started_at']),
                    updated_at=_epoch_to_iso(row['ended_at'] or row['started_at']),
                    turns=row['message_count'] or 0,
                    model=row['model'],
                    cwd=None,
                    first_user_msg=first_user or '',
                    body=body,
                )
        finally:
            conn.close()

    def get_session_messages(self, session_id: str) -> list[dict]:
        # Strip prefix if present
        sid = session_id.split(':', 1)[1] if session_id.startswith('hermes:') else session_id
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT role, content, timestamp, tool_name FROM messages "
                "WHERE session_id=? ORDER BY timestamp", (sid,)
            )
            return [
                {
                    'role': r['role'],
                    'content': r['content'],
                    'timestamp': _epoch_to_iso(r['timestamp']),
                    'tool_name': r['tool_name'],
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()
