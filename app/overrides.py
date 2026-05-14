"""Overrides store: per-session category, group, and hidden flags."""
from __future__ import annotations

import json
from typing import Iterable, Optional

from .models import UnifiedSession
from .storage import BlobSnapshotCache

CATS_BLOB = 'overrides/cats.json'
GROUPS_BLOB = 'overrides/groups.json'
HIDDEN_BLOB = 'overrides/hidden.json'


class OverridesStore:
    def __init__(self, storage: BlobSnapshotCache) -> None:
        self.storage = storage
        self.cats: dict[str, str] = {}
        self.groups: dict[str, str] = {}
        self.hidden: set[str] = set()
        self._loaded = False

    # ---- internal ----
    def _read_json(self, blob_path: str, default):
        try:
            if not self.storage.exists(blob_path):
                return default
            return json.loads(self.storage.read_text(blob_path))
        except Exception:
            return default

    # ---- public ----
    def load(self) -> dict:
        self.cats = dict(self._read_json(CATS_BLOB, {}) or {})
        self.groups = dict(self._read_json(GROUPS_BLOB, {}) or {})
        hidden_obj = self._read_json(HIDDEN_BLOB, {'hidden': []}) or {}
        self.hidden = set(hidden_obj.get('hidden', []) or [])
        self._loaded = True
        return {'cats': self.cats, 'groups': self.groups, 'hidden': self.hidden}

    def set_cat(self, uid: str, cat: Optional[str]) -> None:
        if cat is None or cat == '':
            self.cats.pop(uid, None)
        else:
            self.cats[uid] = cat

    def set_group(self, uid: str, gid: Optional[str]) -> None:
        if gid is None or gid == '':
            self.groups.pop(uid, None)
        else:
            self.groups[uid] = gid

    def hide(self, uid: str) -> None:
        self.hidden.add(uid)

    def unhide(self, uid: str) -> None:
        self.hidden.discard(uid)

    def save_all(self) -> None:
        self.storage.write_text(CATS_BLOB, json.dumps(self.cats, indent=2, sort_keys=True))
        self.storage.write_text(GROUPS_BLOB, json.dumps(self.groups, indent=2, sort_keys=True))
        self.storage.write_text(
            HIDDEN_BLOB,
            json.dumps({'hidden': sorted(self.hidden)}, indent=2),
        )

    def apply(self, sessions: list[UnifiedSession]) -> list[UnifiedSession]:
        for s in sessions:
            if s.id in self.cats:
                s.cat = self.cats[s.id]
            if s.id in self.groups:
                s.group_id = self.groups[s.id]
            if s.id in self.hidden:
                s.hidden = True
        return sessions

    def gc(self, existing_ids: Iterable[str]) -> int:
        existing = set(existing_ids)
        pruned = 0
        for d in (self.cats, self.groups):
            for k in list(d.keys()):
                if k not in existing:
                    del d[k]
                    pruned += 1
        for k in list(self.hidden):
            if k not in existing:
                self.hidden.discard(k)
                pruned += 1
        return pruned
