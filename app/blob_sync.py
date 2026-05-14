"""Pull session snapshots from Azure Blob to local filesystem on startup + periodically."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

REFRESH_INTERVAL = float(os.getenv('AGENTDASH_REFRESH_INTERVAL', '300'))  # 5 min
SNAP_DIR = Path(os.getenv('AGENTDASH_SNAP_DIR', '/tmp/snap'))


def _get_storage():
    """Return a BlobSnapshotCache or None if not configured."""
    blob_url = os.getenv('AGENTDASH_BLOB_URL')
    container = os.getenv('AGENTDASH_BLOB_CONTAINER', 'agent-sessions')
    if not blob_url:
        return None
    try:
        from app.storage import BlobSnapshotCache
    except Exception as e:  # pragma: no cover
        log.warning('storage module not available: %s', e)
        return None
    return BlobSnapshotCache(blob_url, container, cache_dir=str(SNAP_DIR))


def pull_once() -> dict:
    """Pull snapshots; return dict of source -> local path (or error str)."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / 'openclaw').mkdir(parents=True, exist_ok=True)
    storage = _get_storage()
    out: dict = {}
    if storage is None:
        log.info('AGENTDASH_BLOB_URL not set; skipping blob pull (local files only)')
        return out
    # Hermes
    try:
        p = storage.download_if_changed('hermes/snap.db', 'hermes.db')
        out['hermes'] = str(p)
    except Exception as e:
        log.warning('hermes pull failed: %s', e)
        out['hermes_err'] = str(e)
    # GHCP
    try:
        p = storage.download_if_changed('ghcp/snap.db', 'ghcp.db')
        out['ghcp'] = str(p)
    except Exception as e:
        log.warning('ghcp pull failed: %s', e)
        out['ghcp_err'] = str(e)
    # OpenClaw — list and pull each jsonl
    try:
        for name in storage.list_blobs('openclaw/sessions/'):
            if not name.endswith('.jsonl'):
                continue
            local_name = 'openclaw/' + Path(name).name
            try:
                storage.download_if_changed(name, local_name)
            except Exception as e:
                log.warning('openclaw pull %s failed: %s', name, e)
        out['openclaw'] = str(SNAP_DIR / 'openclaw')
    except Exception as e:
        log.warning('openclaw list failed: %s', e)
        out['openclaw_err'] = str(e)
    return out


_started = False
_lock = threading.Lock()


def start_background_refresh(app=None) -> None:
    """Start a daemon thread that re-pulls blobs every REFRESH_INTERVAL seconds."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def _loop():
        while True:
            time.sleep(REFRESH_INTERVAL)
            try:
                pull_once()
                # invalidate the in-process session cache, if app exposed one
                if app is not None and hasattr(app.state, 'cache'):
                    app.state.cache.clear()
                log.info('blob refresh done')
            except Exception as e:  # pragma: no cover
                log.exception('blob refresh failed: %s', e)

    t = threading.Thread(target=_loop, name='blob-refresh', daemon=True)
    t.start()
