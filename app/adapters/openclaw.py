"""OpenClaw adapter - reads .jsonl session files from a directory."""
from __future__ import annotations

import json
import os
import glob
from datetime import datetime, timezone
from typing import Iterator, Optional

from app.adapters.base import Adapter, SchemaMismatchError
from app.models import UnifiedSession, truncate


def _normalize_ts(ts) -> str:
    if ts is None or ts == '':
        return ''
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (OSError, ValueError):
            return ''
    return str(ts)


def _read_jsonl(path: str) -> list[dict]:
    msgs = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        msgs.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return msgs


class OpenClawAdapter(Adapter):
    source = 'openclaw'

    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir

    def schema_check(self) -> None:
        if not os.path.isdir(self.sessions_dir):
            return  # OK - missing dir is fine
        files = sorted(glob.glob(os.path.join(self.sessions_dir, '*.jsonl')))
        if not files:
            return
        # Peek first non-empty line of first file
        with open(files[0], 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise SchemaMismatchError(
                        f'OpenClaw file {files[0]}: invalid JSON: {e}') from e
                if not isinstance(obj, dict) or 'role' not in obj:
                    raise SchemaMismatchError(
                        f'OpenClaw file {files[0]}: expected dict with "role" key')
                return

    def list_sessions(self) -> Iterator[UnifiedSession]:
        if not os.path.isdir(self.sessions_dir):
            return
        files = sorted(glob.glob(os.path.join(self.sessions_dir, '*.jsonl')))
        for path in files:
            sid = os.path.splitext(os.path.basename(path))[0]
            msgs = _read_jsonl(path)
            first_user = ''
            for m in msgs:
                if m.get('role') == 'user' and m.get('content'):
                    first_user = str(m['content'])
                    break
            title = truncate(first_user, 80) or sid
            ts_first = msgs[0].get('timestamp') if msgs else None
            ts_last = msgs[-1].get('timestamp') if msgs else None
            body = '\n\n'.join(str(m.get('content', '')) for m in msgs[:10])
            yield UnifiedSession(
                id=f'openclaw:{sid}',
                source=self.source,
                title=title,
                created_at=_normalize_ts(ts_first),
                updated_at=_normalize_ts(ts_last),
                turns=len(msgs),
                model=None,
                cwd=None,
                first_user_msg=first_user,
                body=body,
            )

    def get_session_messages(self, session_id: str) -> list[dict]:
        sid = session_id.split(':', 1)[1] if session_id.startswith('openclaw:') else session_id
        path = os.path.join(self.sessions_dir, f'{sid}.jsonl')
        msgs = _read_jsonl(path)
        out = []
        for m in msgs:
            out.append({
                'role': m.get('role'),
                'content': m.get('content', ''),
                'timestamp': _normalize_ts(m.get('timestamp')),
            })
        return out
