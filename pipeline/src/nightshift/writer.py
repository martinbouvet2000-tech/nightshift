"""Vault writer enforcing the note contract.

Every note written through :class:`VaultWriter`:
- has YAML frontmatter with ``tags`` (block list), ``created``, ``updated``,
  ``type``, ``source`` and ``score``
- starts its body with an H1 identical to the file name
- is written atomically, under the vault, with a sanitised file name
- only contains wikilinks to notes that exist (see :meth:`VaultWriter.link`)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from nightshift import frontmatter
from nightshift.frontmatter import normalize_tags
from nightshift.fsutil import atomic_write_text, safe_join, sanitize_filename

log = logging.getLogger(__name__)

REQUIRED_KEYS = ("tags", "created", "updated", "type", "source", "score")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def neutralize_links(text: str) -> str:
    """Stop user/model text from creating accidental wikilinks or headings."""
    text = (text or "").replace("[[", "[ [").replace("]]", "] ]")
    return re.sub(r"(?m)^(\s*)#", r"\1\\#", text)


def find_wikilinks(text: str) -> list[str]:
    return [m.strip() for m in _WIKILINK.findall(text or "")]


class VaultWriter:
    def __init__(self, vault: str | Path, folders: dict[str, str], dry_run: bool = False,
                 today: date | None = None):
        self.vault = Path(vault)
        self.folders = dict(folders)
        self.dry_run = dry_run
        self.today = (today or date.today()).isoformat()
        self.planned: dict[Path, str] = {}
        self.written: list[Path] = []

    # --- paths -----------------------------------------------------------------

    def folder(self, kind: str) -> Path:
        rel = self.folders.get(kind, kind)
        parts = [sanitize_filename(p) for p in re.split(r"[\\/]+", str(rel)) if p.strip()]
        return safe_join(self.vault, *parts) if parts else self.vault.resolve()

    def path(self, kind: str, stem: str) -> Path:
        if sanitize_filename(stem) != stem:
            raise ValueError(f"unsafe note name: {stem!r}")
        return safe_join(self.folder(kind), f"{stem}.md")

    def exists(self, kind: str, stem: str) -> bool:
        try:
            p = self.path(kind, stem)
        except ValueError:
            return False
        return p in self.planned or p.exists()

    def link(self, kind: str, stem: str) -> str:
        """Wikilink if the target exists (or is planned in a dry run), else plain text."""
        return f"[[{stem}]]" if self.exists(kind, stem) else stem

    # --- reading -----------------------------------------------------------------

    def read(self, kind: str, stem: str) -> tuple[dict[str, Any], str]:
        p = self.path(kind, stem)
        if p in self.planned:
            return frontmatter.parse(self.planned[p])
        if p.exists():
            return frontmatter.parse(p.read_text(encoding="utf-8", errors="replace"))
        return {}, ""

    def iter_notes(self, kind: str) -> Iterator[tuple[str, dict[str, Any]]]:
        seen: set[Path] = set()
        folder = self.folder(kind)
        for p, content in list(self.planned.items()):
            if p.parent == folder:
                seen.add(p)
                yield p.stem, frontmatter.parse(content)[0]
        if folder.is_dir():
            for p in sorted(folder.glob("*.md")):
                if p.resolve() in seen:
                    continue
                try:
                    meta, _ = frontmatter.parse(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                yield p.stem, meta

    # --- writing -----------------------------------------------------------------

    def write(self, kind: str, stem: str, meta: dict[str, Any], body: str) -> Path:
        p = self.path(kind, stem)
        old_meta, _ = self.read(kind, stem)
        tags = normalize_tags(list(meta.get("tags") or [])) or [kind]
        ordered: dict[str, Any] = {
            "tags": tags,
            "created": old_meta.get("created") or meta.get("created") or self.today,
            "updated": self.today,
            "type": meta.get("type", kind),
            "source": meta.get("source", "nightshift"),
            "score": int(meta.get("score", 0) or 0),
        }
        for k, v in meta.items():
            if k not in ordered:
                ordered[k] = v
        content = frontmatter.dump(ordered) + f"\n# {stem}\n\n" + body.strip() + "\n"
        if self.dry_run:
            self.planned[p] = content
        else:
            atomic_write_text(p, content)
            self.planned.pop(p, None)
        self.written.append(p)
        return p
