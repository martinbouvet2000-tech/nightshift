"""Local drop-folder source.

- ``.txt`` / ``.md``: used directly as transcripts. Markdown files may carry
  YAML frontmatter (title, author, url, published); text files may start with
  ``Key: value`` header lines (Title/Author/URL/Published) followed by a blank line.
- ``.vtt`` / ``.srt``: parsed into plain text.
- audio/video files: handed to the transcribe stage (Whisper, optional).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from nightshift import frontmatter
from nightshift.models import Item
from nightshift.sources.base import Source
from nightshift.transcribe import parse_subtitles

log = logging.getLogger(__name__)

TEXT_EXT = {".txt", ".md"}
SUB_EXT = {".vtt", ".srt"}
MEDIA_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".mp4", ".mkv", ".webm", ".mov",
             ".avi"}
HEADER_RE = re.compile(r"^(title|author|url|published|date)\s*:\s*(.+)$", re.IGNORECASE)


def file_id(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "local-" + h.hexdigest()[:12]


def _parse_txt_header(text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = HEADER_RE.match(lines[i].strip())
        if not m:
            break
        meta[m.group(1).lower()] = m.group(2).strip()
        i += 1
    if meta and (i >= len(lines) or not lines[i].strip()):
        return meta, "\n".join(lines[i:]).strip()
    return {}, text.strip()


def _norm_date(value: object) -> str:
    s = str(value or "").strip()
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else ""


class LocalSource(Source):
    name = "local"

    def _files(self, folder: Path) -> list[Path]:
        it = folder.rglob("*") if self.cfg.get("recursive") else folder.iterdir()
        exts = TEXT_EXT | SUB_EXT | MEDIA_EXT
        return sorted(p for p in it if p.is_file() and p.suffix.lower() in exts
                      and not p.name.startswith("."))

    def fetch(self, limit: int | None = None) -> Iterator[Item]:
        folder = Path(self.cfg.get("drop_folder") or "")
        if not folder.is_dir():
            log.warning("local drop folder does not exist: %s", folder)
            return
        count = 0
        for path in self._files(folder):
            if limit is not None and count >= limit:
                return
            try:
                item = self._load(path)
            except Exception as exc:
                log.warning("skipping %s: %s", path.name, exc)
                continue
            if item is None:
                continue
            count += 1
            yield item

    def _load(self, path: Path) -> Item | None:
        fid = file_id(path)
        if self.state.is_done(self.name, fid):
            return None
        ext = path.suffix.lower()
        mtime = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        # Local paths are deliberately NOT stored as the URL (privacy); only
        # an explicit ``url`` from the file's metadata is kept.
        item = Item(id=fid, source=self.name, title=path.stem, published=mtime)
        if ext in MEDIA_EXT:
            item.media_path = str(path)
            return item
        text = path.read_text(encoding="utf-8", errors="replace")
        meta: dict[str, object] = {}
        if ext == ".md":
            meta, text = frontmatter.parse(text)
        elif ext == ".txt":
            meta, text = _parse_txt_header(text)  # type: ignore[assignment]
        else:
            text = parse_subtitles(text)
        item.transcript = text.strip()
        item.title = str(meta.get("title") or item.title).strip()
        item.author = str(meta.get("author") or "").strip()
        item.url = str(meta.get("url") or item.url).strip()
        item.published = _norm_date(meta.get("published") or meta.get("date")) or item.published
        if not item.transcript:
            log.info("skipping empty file %s", path.name)
            return None
        return item


__all__ = ["LocalSource", "file_id"]
