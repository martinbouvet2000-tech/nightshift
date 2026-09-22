from __future__ import annotations

from nightshift.sources import LocalSource, StateStore, YouTubeSource
from nightshift.transcribe import parse_subtitles


def test_parse_srt_and_vtt():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nHello there\n\n2\n00:00:02,000 --> 00:00:03,000\nHello there\n\n3\n00:00:03,000 --> 00:00:04,000\n<i>General</i> Kenobi\n"
    assert parse_subtitles(srt) == "Hello there General Kenobi"
    vtt = "WEBVTT\n\nNOTE comment\nignored line\n\n00:00.000 --> 00:01.000\nHi\n"
    assert parse_subtitles(vtt) == "Hi"


def test_local_source_formats_and_state(tmp_path):
    (tmp_path / "a.md").write_text("---\ntitle: From Meta\nauthor: Someone\npublished: 2026-01-05\n---\nBody text here.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Title: Header Title\nAuthor: Other\n\nSome transcript.", encoding="utf-8")
    (tmp_path / "c.txt").write_text("Plain text with: a colon but no header.", encoding="utf-8")
    (tmp_path / "d.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nSubtitle words\n", encoding="utf-8")
    (tmp_path / "e.mp3").write_bytes(b"\x00\x01")
    (tmp_path / "ignored.pdf").write_bytes(b"%PDF")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")

    state = StateStore(tmp_path / "state" / "state.json")
    items = {it.title: it for it in LocalSource({"drop_folder": str(tmp_path)}, state).fetch()}
    assert set(items) == {"From Meta", "Header Title", "c", "d", "e"}
    assert items["From Meta"].author == "Someone" and items["From Meta"].published == "2026-01-05"
    assert items["Header Title"].transcript == "Some transcript."
    assert items["c"].transcript.startswith("Plain text with")
    assert items["d"].transcript == "Subtitle words"
    assert items["e"].media_path and not items["e"].transcript
    assert all(it.url == "" for it in items.values())  # local paths never leak into notes

    state.mark_done("local", items["From Meta"].id)
    state.save()
    again = StateStore(tmp_path / "state" / "state.json")
    titles = {it.title for it in LocalSource({"drop_folder": str(tmp_path)}, again).fetch()}
    assert "From Meta" not in titles and len(titles) == 4


def test_local_source_missing_folder(tmp_path):
    assert list(LocalSource({"drop_folder": str(tmp_path / "nope")}, StateStore(None)).fetch()) == []


class FakeYouTube(YouTubeSource):
    def __init__(self, cfg, state, videos, transcripts):
        super().__init__(cfg, state)
        self.videos = videos
        self.transcripts = transcripts
        self.fetched = []

    def list_videos(self, source_url, max_n):
        return self.videos[:max_n]

    def fetch_transcript(self, video_id):
        self.fetched.append(video_id)
        return self.transcripts.get(video_id, ""), "en", {"upload_date": "20260102"}


def test_youtube_skips_done_and_retries_failures(tmp_path):
    videos = [{"id": v, "title": f"Video {v}", "uploader": "Chan", "url": f"https://example.com/{v}"}
              for v in ("v1", "v2", "v3")]
    state = StateStore(tmp_path / "s.json")
    state.mark_done("youtube", "v1")
    cfg = {"urls": ["https://example.com/channel"], "max_per_source": 10, "max_new_per_run": 10,
           "max_attempts": 2}
    src = FakeYouTube(cfg, state, videos, {"v2": "a transcript that is long enough " * 3})
    items = list(src.fetch())
    assert [i.id for i in items] == ["v2"]
    assert items[0].published == "2026-01-02" and items[0].author == "Chan"
    assert "v1" not in src.fetched
    assert state.attempts("youtube", "v3") == 1
    list(src.fetch())
    assert state.attempts("youtube", "v3") == 2
    src.fetched.clear()
    list(src.fetch())
    assert "v3" not in src.fetched  # gave up after max_attempts


def test_youtube_no_urls(tmp_path):
    assert list(YouTubeSource({"urls": []}, StateStore(None)).fetch()) == []
