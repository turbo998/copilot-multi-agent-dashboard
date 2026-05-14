"""FastAPI app for the multi-agent dashboard."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.adapters.base import Adapter, SchemaMismatchError
from app.adapters.ghcp import GHCPAdapter
from app.adapters.hermes import HermesAdapter
from app.adapters.openclaw import OpenClawAdapter
from app.models import UnifiedSession

# Phase 2 modules - optional, not yet present.
try:  # pragma: no cover - import guard
    from app import storage  # noqa: F401  TODO: phase2
    from app import overrides  # noqa: F401  TODO: phase2
    from app import heartbeat  # noqa: F401  TODO: phase2
except Exception:  # pragma: no cover
    storage = overrides = heartbeat = None  # type: ignore

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / 'templates'
STATIC_DIR = APP_DIR / 'static'

CACHE_TTL = 60.0


class _SessionCache:
    """Tiny TTL cache for the merged session list per (source,q,limit)."""

    def __init__(self, ttl: float = CACHE_TTL) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[tuple, tuple[float, list[dict]]] = {}

    def get(self, key: tuple) -> Optional[list[dict]]:
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            ts, val = entry
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            return val

    def set(self, key: tuple, val: list[dict]) -> None:
        with self._lock:
            self._data[key] = (time.time(), val)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def _build_default_adapters() -> list[Adapter]:
    hermes_db = os.getenv('AGENTDASH_HERMES_DB', '/tmp/snap/hermes.db')
    ghcp_db = os.getenv('AGENTDASH_GHCP_DB', '/tmp/snap/ghcp.db')
    openclaw_dir = os.getenv('AGENTDASH_OPENCLAW_DIR', '/tmp/snap/openclaw')

    adapters: list[Adapter] = []
    if os.path.exists(hermes_db):
        adapters.append(HermesAdapter(hermes_db))
    else:
        log.warning('Hermes db not found: %s (skipping)', hermes_db)
    if os.path.exists(ghcp_db):
        adapters.append(GHCPAdapter(ghcp_db))
    else:
        log.warning('GHCP db not found: %s (skipping)', ghcp_db)
    if os.path.isdir(openclaw_dir):
        adapters.append(OpenClawAdapter(openclaw_dir))
    else:
        log.warning('OpenClaw dir not found: %s (skipping)', openclaw_dir)
    return adapters


def _collect_sessions(adapters: list[Adapter]) -> list[dict]:
    out: list[dict] = []
    for adapter in adapters:
        try:
            for sess in adapter.list_sessions():
                out.append(sess.to_dict())
        except Exception as e:  # pragma: no cover
            log.exception('Adapter %s failed: %s', adapter.source, e)
    # newest first by updated_at, then created_at
    out.sort(key=lambda s: (s.get('updated_at') or s.get('created_at') or ''), reverse=True)
    return out


def _filter_sessions(sessions: list[dict], source: str, q: str, limit: int) -> list[dict]:
    result = sessions
    if source and source != 'all':
        result = [s for s in result if s.get('source') == source]
    if q:
        ql = q.lower()
        result = [
            s for s in result
            if ql in (s.get('title') or '').lower()
            or ql in (s.get('first_user_msg') or '').lower()
            or ql in (s.get('body') or '').lower()
        ]
    if limit > 0:
        result = result[:limit]
    return result


def _find_adapter(adapters: list[Adapter], full_id: str) -> Optional[Adapter]:
    if ':' in full_id:
        prefix = full_id.split(':', 1)[0]
        for a in adapters:
            if a.source == prefix:
                return a
    return None


def create_app(adapters: Optional[list[Adapter]] = None) -> FastAPI:
    if adapters is None:
        adapters = _build_default_adapters()

    app = FastAPI(title='Agent Dashboard')
    app.state.adapters = adapters
    app.state.cache = _SessionCache()

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.state.templates = templates

    if STATIC_DIR.is_dir():
        app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

    def _all_sessions_cached() -> list[dict]:
        cache: _SessionCache = app.state.cache
        cached = cache.get(('__all__',))
        if cached is not None:
            return cached
        data = _collect_sessions(app.state.adapters)
        cache.set(('__all__',), data)
        return data

    @app.get('/healthz')
    def healthz() -> dict:
        return {'status': 'ok'}

    @app.get('/api/sessions')
    def api_sessions(source: str = 'all', q: str = '', limit: int = 200) -> JSONResponse:
        all_sessions = _all_sessions_cached()
        filtered = _filter_sessions(all_sessions, source, q, limit)
        return JSONResponse(filtered)

    @app.get('/api/sessions/{full_id}/messages')
    def api_session_messages(full_id: str) -> JSONResponse:
        adapter = _find_adapter(app.state.adapters, full_id)
        if adapter is None:
            raise HTTPException(status_code=404, detail='unknown source for id')
        try:
            msgs = adapter.get_session_messages(full_id)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=str(e))
        return JSONResponse(msgs)

    @app.get('/', response_class=HTMLResponse)
    def index(request: Request, source: str = 'all', q: str = '') -> HTMLResponse:
        all_sessions = _all_sessions_cached()
        filtered = _filter_sessions(all_sessions, source, q, 200)
        return templates.TemplateResponse(
            request,
            'index.html',
            {
                'sessions': filtered,
                'source': source,
                'q': q,
                'sources': ['all', 'ghcp', 'hermes', 'openclaw'],
                'total': len(all_sessions),
            },
        )

    @app.get('/session/{full_id}', response_class=HTMLResponse)
    def session_detail(request: Request, full_id: str) -> HTMLResponse:
        adapter = _find_adapter(app.state.adapters, full_id)
        if adapter is None:
            raise HTTPException(status_code=404, detail='session not found')
        # find session metadata
        all_sessions = _all_sessions_cached()
        session = next((s for s in all_sessions if s.get('id') == full_id), None)
        if session is None:
            raise HTTPException(status_code=404, detail='session not found')
        try:
            messages = adapter.get_session_messages(full_id)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=str(e))
        return templates.TemplateResponse(
            request,
            'session.html',
            {
                'session': session,
                'messages': messages,
            },
        )

    return app


# Module-level app for `uvicorn app.main:app`.
# In production: pulls snapshots from Blob on startup, then refreshes in background.
def _bootstrap_and_create() -> FastAPI:
    if os.getenv('AGENTDASH_BLOB_URL'):
        try:
            from app import blob_sync
            blob_sync.pull_once()
        except Exception as e:
            log.warning('initial blob pull failed: %s', e)
    a = create_app()
    if os.getenv('AGENTDASH_BLOB_URL'):
        try:
            from app import blob_sync
            blob_sync.start_background_refresh(a)
        except Exception as e:  # pragma: no cover
            log.warning('failed to start blob refresh: %s', e)
    return a


# Always export `app` so `uvicorn app.main:app` works in container.
app = _bootstrap_and_create()
