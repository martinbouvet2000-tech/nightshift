"""Filesystem safety helpers: filename sanitisation, traversal-safe joins,
atomic writes and small JSON state files."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Windows reserved device names (case-insensitive, with or without extension).
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}

# Path separators, Windows-illegal characters, control chars, and characters
# that break Obsidian wikilinks ([ ] # ^ |).
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f\[\]#^]')


def sanitize_filename(name: Any, max_len: int = 100, fallback: str = "untitled") -> str:
    """Return a safe, human-readable file stem (no extension).

    - removes path separators and characters illegal on Windows/macOS/Linux
    - collapses any run of dots, so ``..`` can never survive
    - strips leading/trailing dots and whitespace
    - prefixes Windows reserved device names (CON, NUL, COM1...) with ``_``
    - truncates to ``max_len`` characters and never returns an empty string
    """
    s = unicodedata.normalize("NFC", str(name if name is not None else ""))
    s = _BAD_CHARS.sub(" ", s)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    if not s:
        s = fallback
    if s.split(".")[0].strip().upper() in _RESERVED:
        s = "_" + s
    return s


def safe_join(base: str | os.PathLike, *parts: str) -> Path:
    """Join ``parts`` under ``base`` and refuse anything that escapes it."""
    base_r = Path(base).resolve()
    target = base_r.joinpath(*parts).resolve()
    if target != base_r and base_r not in target.parents:
        raise ValueError(f"path escapes base directory: {target}")
    return target


def atomic_write_text(path: str | os.PathLike, content: str, encoding: str = "utf-8",
                      retries: int = 3) -> Path:
    """Write ``content`` to ``path`` atomically (temp file in same dir + replace).

    Either the whole new content lands, or the previous file is left untouched.
    Retries the final rename a few times because Windows can briefly lock files
    that are open in an editor or being indexed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(retries):
            try:
                os.replace(tmp, path)
                return path
            except PermissionError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.2 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path  # pragma: no cover


def load_json(path: str | os.PathLike, default: Any) -> Any:
    """Read a JSON file, returning ``default`` if missing or corrupt."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt state must never abort a run
        log.warning("could not read %s (%s); starting fresh", p.name, exc)
        return default


def save_json(path: str | os.PathLike, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
