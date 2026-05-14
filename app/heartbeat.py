"""Heartbeat tracking for ingester sources."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .storage import BlobSnapshotCache

SOURCES = ('ghcp', 'hermes', 'openclaw')


def _blob_for(source: str) -> str:
    return f"heartbeats/{source}.txt"


class HeartbeatStore:
    def __init__(self, storage: BlobSnapshotCache) -> None:
        self.storage = storage

    def write(self, source: str, ts: Optional[datetime] = None) -> None:
        if ts is None:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self.storage.write_text(_blob_for(source), ts.isoformat())

    def read_all(self) -> dict[str, Optional[datetime]]:
        out: dict[str, Optional[datetime]] = {}
        for src in SOURCES:
            out[src] = self._read_one(src)
        return out

    def _read_one(self, source: str) -> Optional[datetime]:
        try:
            if not self.storage.exists(_blob_for(source)):
                return None
            txt = self.storage.read_text(_blob_for(source)).strip()
            if not txt:
                return None
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def status(self, thresholds: dict[str, timedelta]) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        beats = self.read_all()
        out: dict[str, str] = {}
        for src in SOURCES:
            ts = beats.get(src)
            if ts is None:
                out[src] = 'missing'
                continue
            thr = thresholds.get(src, timedelta(minutes=5))
            out[src] = 'ok' if (now - ts) <= thr else 'stale'
        return out
