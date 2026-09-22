"""Core data model shared by sources and stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Item:
    """One piece of content flowing through the pipeline.

    Sources fill the first block of fields; stages fill the rest.
    """

    id: str
    source: str
    url: str = ""
    title: str = ""
    author: str = ""
    published: str = ""  # ISO date (YYYY-MM-DD) when known
    transcript: str = ""
    media_path: str | None = None
    language: str = ""

    # Filled by stages
    categories: list[str] = field(default_factory=list)
    extraction: dict[str, Any] = field(default_factory=dict)
    backend: str = ""
    signal_score: int = 0
    keywords: list[str] = field(default_factory=list)
    note_stem: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
