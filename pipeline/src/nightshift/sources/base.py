"""Source interface and the shared sync-state store."""

from __future__ import annotations

import abc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nightshift.fsutil import load_json, save_json
from nightshift.models import Item

DONE = "done"


class StateStore:
    """Persistent record of processed item IDs, per source.

    Format: ``{"<source>": {"<item id>": "done" | <failed attempts>}}``.
    """

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.data: dict[str, dict[str, Any]] = load_json(self.path, {}) if self.path else {}
        if not isinstance(self.data, dict):
            self.data = {}

    def _bucket(self, source: str) -> dict[str, Any]:
        return self.data.setdefault(source, {})

    def is_done(self, source: str, item_id: str) -> bool:
        return self._bucket(source).get(item_id) == DONE

    def attempts(self, source: str, item_id: str) -> int:
        v = self._bucket(source).get(item_id)
        return v if isinstance(v, int) else 0

    def mark_done(self, source: str, item_id: str) -> None:
        self._bucket(source)[item_id] = DONE

    def bump_failure(self, source: str, item_id: str) -> int:
        n = self.attempts(source, item_id) + 1
        self._bucket(source)[item_id] = n
        return n

    def save(self) -> None:
        if self.path:
            save_json(self.path, self.data)


class Source(abc.ABC):
    """A pluggable content source.

    Subclasses set ``name`` and implement ``fetch``, yielding :class:`Item`
    objects with at least ``id``, ``source`` and either ``transcript`` or
    ``media_path``. Sources must skip IDs that ``state.is_done`` reports and
    must never raise for a single bad item (log and continue instead).
    """

    name: str = "base"

    def __init__(self, cfg: dict[str, Any], state: StateStore):
        self.cfg = cfg or {}
        self.state = state

    @abc.abstractmethod
    def fetch(self, limit: int | None = None) -> Iterator[Item]:
        raise NotImplementedError
