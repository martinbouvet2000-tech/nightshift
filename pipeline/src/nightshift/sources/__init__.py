"""Source registry. Third-party sources can call ``register_source``."""

from __future__ import annotations

from nightshift.sources.base import Source, StateStore
from nightshift.sources.local import LocalSource
from nightshift.sources.youtube import YouTubeSource

SOURCES: dict[str, type[Source]] = {
    LocalSource.name: LocalSource,
    YouTubeSource.name: YouTubeSource,
}


def register_source(cls: type[Source]) -> type[Source]:
    SOURCES[cls.name] = cls
    return cls


__all__ = ["SOURCES", "Source", "StateStore", "register_source", "LocalSource", "YouTubeSource"]
