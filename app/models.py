"""Unified data model for cross-agent sessions."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional


def truncate(s: Optional[str], n: int) -> str:
    """Safely truncate a string. None -> ''."""
    if not s:
        return ''
    if len(s) <= n:
        return s
    return s[:n]


@dataclass
class UnifiedSession:
    id: str
    source: str
    title: str
    created_at: str
    updated_at: str
    turns: int
    model: Optional[str]
    cwd: Optional[str]
    first_user_msg: str
    body: str
    cat: str = 'uncategorized'
    group_id: Optional[str] = None
    hidden: bool = False

    def __post_init__(self) -> None:
        self.first_user_msg = truncate(self.first_user_msg, 240)
        self.body = truncate(self.body, 8000)

    def to_dict(self) -> dict:
        return asdict(self)
