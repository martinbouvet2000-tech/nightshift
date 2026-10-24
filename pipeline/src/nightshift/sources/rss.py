"""RSS / Atom source: one item per feed entry, standard library only.

Reads RSS 2.0, RSS 1.0 (RDF) and Atom. The text of an entry is its full
content (``content:encoded`` or Atom ``content``), falling back to the
description or summary, with HTML reduced to plain text. Podcast feeds that
publish a transcript (``<podcast:transcript>``, the Podcasting 2.0 tag) get
that transcript instead of the show notes.

A feed is untrusted input: only http(s) URLs are fetched, responses are capped
in size, and a document that declares XML entities is refused outright (the
classic entity-expansion attacks need them, and real feeds never do).
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from nightshift import __version__
from nightshift.models import Item
from nightshift.sources.base import Source
from nightshift.transcribe import parse_subtitles

log = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
TRANSCRIPT_TYPES = ("text/vtt", "application/x-subrip", "application/srt", "text/srt",
                    "text/plain", "text/html")


class FeedError(Exception):
    """A feed that cannot be fetched or parsed. Logged per feed, never fatal."""


# --- small helpers -------------------------------------------------------------

def _local(tag: str) -> str:
    """Element name without its namespace: '{http://...}encoded' -> 'encoded'."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre"}
    SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text from an HTML fragment: blocks become lines, scripts and styles vanish."""
    if "<" not in html:
        return re.sub(r"[ \t]+", " ", unescape(html)).strip()
    p = _TextExtractor()
    p.feed(html)
    p.close()
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in "".join(p.parts).splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_date(value: str) -> str:
    """ISO date (YYYY-MM-DD) from an RFC 822 (RSS) or ISO 8601 (Atom) timestamp, else ''."""
    v = (value or "").strip()
    if not v:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
    if m:
        return m.group(1)
    try:
        return parsedate_to_datetime(v).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(v).date().isoformat()
    except ValueError:
        return ""


def parse_feed(data: bytes) -> tuple[dict[str, str], list[ET.Element]]:
    """Return (feed info, entry elements). Raises FeedError on unsafe or invalid XML."""
    head = data[:4096].lower()
    if b"<!entity" in head or b"<!entity" in data.lower():
        raise FeedError("feed declares XML entities: refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError(f"invalid XML: {exc}") from exc
    kind = _local(root.tag)
    if kind not in ("rss", "feed", "RDF"):
        raise FeedError(f"not a feed (root element <{kind}>)")
    channel = _child(root, "channel") if kind != "feed" else root
    channel = channel if channel is not None else root
    info = {
        "title": _text(_child(channel, "title")),
        "language": _text(_child(channel, "language")) or root.get("{http://www.w3.org/XML/1998/namespace}lang", ""),
        "author": _text(_child(channel, "author")) or _text(_child(channel, "creator")),
    }
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    return info, entries


def _link(entry: ET.Element) -> str:
    for c in entry:
        if _local(c.tag) != "link":
            continue
        href = c.get("href")
        if href is not None:  # Atom
            if c.get("rel", "alternate") == "alternate":
                return href.strip()
            continue
        if (c.text or "").strip():  # RSS
            return c.text.strip()
    return ""


def _transcript_ref(entry: ET.Element) -> tuple[str, str] | None:
    """(url, mime type) of the best <podcast:transcript>, preferring timed formats."""
    refs = [(c.get("url", ""), (c.get("type") or "").lower()) for c in entry
            if _local(c.tag) == "transcript" and c.get("url")]
    for wanted in TRANSCRIPT_TYPES:
        for url, typ in refs:
            if typ == wanted:
                return url, typ
    return None


# --- the source ----------------------------------------------------------------

class RSSSource(Source):
    name = "rss"

    # --- network layer (overridable in tests) --------------------------------

    def fetch_url(self, url: str) -> bytes:
        if not re.match(r"https?://", url, re.I):
            raise FeedError(f"only http(s) URLs are fetched: {url}")
        req = urllib.request.Request(url, headers={
            "User-Agent": f"nightshift/{__version__} (+https://github.com/martinbouvet2000-tech/nightshift)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
        })
        timeout = float(self.cfg.get("timeout_seconds", 20))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme checked)
                data = resp.read(MAX_BYTES + 1)
        except OSError as exc:
            raise FeedError(str(exc)) from exc
        if len(data) > MAX_BYTES:
            raise FeedError(f"response larger than {MAX_BYTES // (1024 * 1024)} MB")
        return data

    # --- entry -> item -------------------------------------------------------

    def _entry_text(self, entry: ET.Element) -> str:
        for names in (("encoded",), ("content",), ("description", "summary")):
            el = _child(entry, *names)
            if el is not None:
                # Atom xhtml content arrives as child elements, everything else as text.
                raw = ET.tostring(el, encoding="unicode", method="html") if len(el) else (el.text or "")
                text = html_to_text(raw)
                if text:
                    return text
        return ""

    def _transcript(self, entry: ET.Element) -> str:
        if not self.cfg.get("podcast_transcripts", True):
            return ""
        ref = _transcript_ref(entry)
        if not ref:
            return ""
        url, typ = ref
        try:
            raw = self.fetch_url(url).decode("utf-8", errors="replace")
        except FeedError as exc:
            log.info("rss: transcript unavailable (%s): %s", url, exc)
            return ""
        if typ == "text/html":
            return html_to_text(raw)
        if typ == "text/plain":
            return raw.strip()
        return parse_subtitles(raw)

    def entry_to_item(self, feed_url: str, info: dict[str, str], entry: ET.Element) -> Item | None:
        title = html_to_text(_text(_child(entry, "title")))
        link = _link(entry)
        key = _text(_child(entry, "guid", "id")) or link or f"{title}|{_text(_child(entry, 'pubDate', 'published', 'updated', 'date'))}"
        if not key.strip("|"):
            raise ValueError("entry has no guid, id, link or title")
        item_id = hashlib.sha1(f"{feed_url}\n{key}".encode()).hexdigest()[:16]
        if self.state.is_done(self.name, item_id):
            return None
        text = self._transcript(entry) or self._entry_text(entry)
        if len(text) < int(self.cfg.get("min_chars", 200)):
            # Title-only or teaser entries carry nothing to extract; they will not grow later.
            self.state.mark_done(self.name, item_id)
            log.info("rss: skipping %r: %d chars of text (min_chars)", title or link, len(text))
            return None
        author = _text(_child(entry, "author", "creator"))
        if _child(entry, "author") is not None and _child(_child(entry, "author"), "name") is not None:
            author = _text(_child(_child(entry, "author"), "name"))
        return Item(
            id=item_id, source=self.name, url=link, title=title or link or item_id,
            author=author or info.get("author") or info.get("title", ""),
            published=parse_date(_text(_child(entry, "pubDate", "published", "updated", "date"))),
            transcript=text, language=(info.get("language") or "").split("-")[0].lower(),
        )

    # --- Source API ------------------------------------------------------------

    def fetch(self, limit: int | None = None) -> Iterator[Item]:
        urls = list(self.cfg.get("urls") or [])
        if not urls:
            log.info("rss: no urls configured")
            return
        max_per = int(self.cfg.get("max_per_feed", 20))
        max_new = int(self.cfg.get("max_new_per_run", 20))
        if limit is not None:
            max_new = min(max_new, limit)
        produced = 0
        for url in urls:
            if produced >= max_new:
                return
            try:
                info, entries = parse_feed(self.fetch_url(url))
            except FeedError as exc:
                log.warning("rss: skipping feed %s: %s", url, exc)
                continue
            for entry in entries[:max_per]:
                if produced >= max_new:
                    return
                try:
                    item = self.entry_to_item(url, info, entry)
                except Exception as exc:  # one bad entry never stops the feed
                    log.warning("rss: skipping a malformed entry in %s: %s", url, exc)
                    continue
                if item is None:
                    continue
                produced += 1
                yield item
