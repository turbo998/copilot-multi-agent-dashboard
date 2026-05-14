"""Adapter base class and shared exceptions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from app.models import UnifiedSession


class SchemaMismatchError(RuntimeError):
    """Raised when a backing data store's schema doesn't match adapter expectations."""


class Adapter(ABC):
    source: str = ''  # override in subclass

    @abstractmethod
    def list_sessions(self) -> Iterator[UnifiedSession]:
        ...

    @abstractmethod
    def get_session_messages(self, session_id: str) -> list[dict]:
        ...

    @abstractmethod
    def schema_check(self) -> None:
        ...
