"""YouTube source: latest videos of configured channels/playlists, with
native subtitles (manual first, then automatic) fetched through yt-dlp.

yt-dlp is an optional dependency: ``pip install 'nightshift[youtube]'``.
Videos with no usable subtitles are retried on later runs, up to
``max_attempts``, then given up on.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nightshift.models import Item
from nightshift.sources.base import Source
from nightshift.transcribe import parse_subtitles

log = logging.getLogger(__name__)


def ytdlp_available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def _normalize_source_url(url: str) -> str:
    """For a channel handle URL, target its /videos tab (skips shorts/streams)."""
    if "/@" in url and "/videos" not in url and "list=" not in url:
        return url.rstrip("/") + "/videos"
    return url


def _fmt_date(upload_date: Any) -> str:
    s = str(upload_date or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.fullmatch(r"\d{8}", s) else ""


class YouTubeSource(Source):
    name = "youtube"

    # --- network layer (overridable in tests) --------------------------------

    def _ydl_opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "ignoreerrors": True}
        browser = self.cfg.get("cookies_from_browser")
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
        opts.update(extra)
        return opts

    def list_videos(self, source_url: str, max_n: int) -> list[dict[str, Any]]:
        """Return [{id, title, uploader, url}] for the latest ``max_n`` videos."""
        import yt_dlp  # type: ignore[import-not-found]

        opts = self._ydl_opts(extract_flat="in_playlist", playlistend=max_n, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(_normalize_source_url(source_url), download=False) or {}
        out = []
        for e in (info.get("entries") or [])[:max_n]:
            if not e or not e.get("id"):
                continue
            out.append({
                "id": e["id"],
                "title": (e.get("title") or "").strip(),
                "uploader": (e.get("uploader") or e.get("channel") or info.get("uploader")
                             or info.get("channel") or "").strip(),
                "url": e.get("url") if str(e.get("url", "")).startswith("http")
                else f"https://www.youtube.com/watch?v={e['id']}",
            })
        return out

    def fetch_transcript(self, video_id: str) -> tuple[str, str, dict[str, Any]]:
        """Return (transcript, language, info) using native subtitles only."""
        import yt_dlp  # type: ignore[import-not-found]

        langs = list(self.cfg.get("languages") or ["en"])
        with tempfile.TemporaryDirectory(prefix="nightshift-yt-") as tmp:
            opts = self._ydl_opts(
                skip_download=True, writesubtitles=True, writeautomaticsub=True,
                subtitleslangs=langs, subtitlesformat="vtt",
                outtmpl=str(Path(tmp) / "%(id)s.%(ext)s"),
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                        download=True) or {}
            files = sorted(Path(tmp).glob("*.vtt"))
            # Prefer the configured language order.
            for lang in langs:
                for f in files:
                    if f.name.endswith(f".{lang}.vtt"):
                        text = parse_subtitles(f.read_text(encoding="utf-8", errors="replace"))
                        if len(text) > 50:
                            return text, lang, info
            for f in files:
                text = parse_subtitles(f.read_text(encoding="utf-8", errors="replace"))
                if len(text) > 50:
                    return text, f.suffixes[-2].lstrip(".") if len(f.suffixes) > 1 else "", info
        return "", "", info

    # --- Source API ------------------------------------------------------------

    def fetch(self, limit: int | None = None) -> Iterator[Item]:
        urls = list(self.cfg.get("urls") or [])
        if not urls:
            log.info("youtube: no urls configured")
            return
        if not ytdlp_available() and type(self).list_videos is YouTubeSource.list_videos:
            log.error("youtube: yt-dlp is not installed (pip install 'nightshift[youtube]'); skipping")
            return
        max_per = int(self.cfg.get("max_per_source", 15))
        max_new = int(self.cfg.get("max_new_per_run", 12))
        if limit is not None:
            max_new = min(max_new, limit)
        max_attempts = int(self.cfg.get("max_attempts", 3))
        produced = 0
        for src in urls:
            if produced >= max_new:
                return
            try:
                videos = self.list_videos(src, max_per)
            except Exception as exc:
                log.warning("youtube: could not list %s: %s", src, exc)
                continue
            for v in videos:
                if produced >= max_new:
                    return
                vid = v["id"]
                if self.state.is_done(self.name, vid):
                    continue
                if self.state.attempts(self.name, vid) >= max_attempts:
                    continue
                try:
                    text, lang, info = self.fetch_transcript(vid)
                except Exception as exc:
                    log.warning("youtube: transcript error for %s: %s", vid, exc)
                    text, lang, info = "", "", {}
                if not text:
                    n = self.state.bump_failure(self.name, vid)
                    log.info("youtube: no subtitles for %s (attempt %d/%d)", vid, n, max_attempts)
                    continue
                produced += 1
                yield Item(
                    id=vid, source=self.name, url=v.get("url", ""),
                    title=v.get("title") or info.get("title", "") or vid,
                    author=v.get("uploader") or info.get("uploader", ""),
                    published=_fmt_date(info.get("upload_date")),
                    transcript=text, language=lang,
                )
