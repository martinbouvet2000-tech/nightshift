from __future__ import annotations

from datetime import date

import pytest

from nightshift.config import DEFAULTS, deep_merge
from nightshift.pipeline import run_pipeline
from nightshift.sources import RSSSource, StateStore
from nightshift.sources.rss import FeedError, html_to_text, parse_date, parse_feed

from conftest import assert_links_resolve, assert_note_contract

BODY = ("<p>Spaced repetition schedules reviews at growing intervals, so a card you know well "
        "comes back after weeks while a hard one returns tomorrow. Anki and Mochi both implement "
        "the SM-2 family of algorithms.</p><script>track()</script><p>Second paragraph &amp; more.</p>")

RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
  <title>Learning Notes</title><language>en-us</language>
  <item>
    <title>Why spaced repetition works</title>
    <link>https://example.com/spaced</link>
    <guid>https://example.com/?p=1</guid>
    <pubDate>Tue, 06 Jan 2026 08:00:00 +0000</pubDate>
    <description>Short teaser.</description>
    <content:encoded><![CDATA[{BODY}]]></content:encoded>
  </item>
  <item>
    <title>Just a link</title>
    <link>https://example.com/link-only</link>
    <description>Too short to learn from.</description>
  </item>
  <item>
    <title>Episode 12</title>
    <guid>ep-12</guid>
    <description>Show notes.</description>
    <podcast:transcript url="https://example.com/ep12.vtt" type="text/vtt"/>
    <podcast:transcript url="https://example.com/ep12.html" type="text/html"/>
  </item>
</channel></rss>""".encode()

ATOM = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="fr">
  <title>Atom blog</title>
  <entry>
    <title>Local-first notes</title>
    <id>tag:example.com,2026:1</id>
    <link rel="alternate" href="https://example.com/local-first"/>
    <link rel="edit" href="https://example.com/edit/1"/>
    <author><name>Ada</name></author>
    <updated>2026-02-03T10:00:00Z</updated>
    <content type="html">{BODY.replace('&', '&amp;').replace('<', '&lt;')}</content>
  </entry>
</feed>""".encode()

VTT = ("WEBVTT\n\n00:00.000 --> 00:05.000\nWelcome to episode twelve, where we talk about building a "
       "retrieval pipeline with Postgres and pgvector for a small team.\n\n00:05.000 --> 00:10.000\n"
       "We cover chunking, embeddings and evaluation, and why most teams skip the evaluation part.\n")


class FakeRSS(RSSSource):
    def __init__(self, cfg, state, responses):
        super().__init__(cfg, state)
        self.responses = responses
        self.calls: list[str] = []

    def fetch_url(self, url):
        self.calls.append(url)
        r = self.responses.get(url)
        if r is None:
            raise FeedError(f"unreachable: {url}")
        return r


def _src(tmp_path, responses, **cfg):
    state = StateStore(tmp_path / "state.json")
    conf = {**DEFAULTS["sources"]["rss"], "urls": [u for u in responses if "feed" in u or "atom" in u], **cfg}
    return FakeRSS(conf, state, dict(responses)), state


def test_rss_well_formed_feed_with_podcast_transcript(tmp_path):
    src, _ = _src(tmp_path, {"https://example.com/feed.xml": RSS, "https://example.com/ep12.vtt": VTT.encode()})
    items = {it.title: it for it in src.fetch()}
    assert set(items) == {"Why spaced repetition works", "Episode 12"}, "link-only entry skipped"
    post = items["Why spaced repetition works"]
    assert post.url == "https://example.com/spaced" and post.published == "2026-01-06"
    assert post.language == "en" and post.author == "Learning Notes" and post.source == "rss"
    assert "growing intervals" in post.transcript and "track()" not in post.transcript
    assert "Second paragraph & more." in post.transcript, "full content wins over the teaser"
    ep = items["Episode 12"]
    assert ep.transcript.startswith("Welcome to episode twelve"), "timed transcript preferred over show notes"
    assert "https://example.com/ep12.vtt" in src.calls and "https://example.com/ep12.html" not in src.calls


def test_atom_feed(tmp_path):
    src, _ = _src(tmp_path, {"https://example.com/atom": ATOM})
    [it] = list(src.fetch())
    assert it.title == "Local-first notes" and it.url == "https://example.com/local-first"
    assert it.author == "Ada" and it.published == "2026-02-03" and it.language == "fr"
    assert "growing intervals" in it.transcript


def test_malformed_entry_is_skipped_not_fatal(tmp_path, monkeypatch):
    src, _ = _src(tmp_path, {"https://example.com/feed.xml": RSS})
    real = RSSSource.entry_to_item

    def flaky(self, feed_url, info, entry):
        if "Episode" in "".join(entry.itertext()):
            raise ValueError("broken entry")
        return real(self, feed_url, info, entry)

    monkeypatch.setattr(RSSSource, "entry_to_item", flaky)
    assert [it.title for it in src.fetch()] == ["Why spaced repetition works"]


def test_unreachable_and_invalid_feeds_do_not_stop_the_others(tmp_path):
    feeds = {
        "https://down.example/feed": None,
        "https://broken.example/feed": b"<rss><channel><item>",
        "https://html.example/feed": b"<html><body>not a feed</body></html>",
        "https://example.com/atom": ATOM,
    }
    src = FakeRSS({**DEFAULTS["sources"]["rss"], "urls": list(feeds)}, StateStore(tmp_path / "s.json"), feeds)
    assert [it.title for it in src.fetch()] == ["Local-first notes"]


def test_entity_declarations_are_refused():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]>'
            b'<rss><channel><item><title>&b;</title></item></channel></rss>')
    with pytest.raises(FeedError, match="entities"):
        parse_feed(bomb)


def test_only_http_urls_are_fetched(tmp_path):
    src = RSSSource({}, StateStore(tmp_path / "s.json"))
    with pytest.raises(FeedError, match="http"):
        src.fetch_url("file:///etc/passwd")


def test_ids_are_stable_and_limits_apply(tmp_path):
    feeds = {"https://example.com/feed.xml": RSS}
    first = [it.id for it in _src(tmp_path, feeds, podcast_transcripts=False, min_chars=10)[0].fetch()]
    again = [it.id for it in _src(tmp_path, feeds, podcast_transcripts=False, min_chars=10)[0].fetch()]
    assert first == again and len(first) == 3
    assert len(list(_src(tmp_path, feeds, min_chars=10)[0].fetch(limit=1))) == 1


def test_helpers():
    assert html_to_text("<p>a</p><p>b &amp; c</p>") == "a\n\nb & c"
    assert html_to_text("plain &amp; simple") == "plain & simple"
    assert parse_date("Tue, 06 Jan 2026 08:00:00 +0000") == "2026-01-06"
    assert parse_date("2026-02-03T10:00:00Z") == "2026-02-03"
    assert parse_date("someday") == ""


def test_rss_end_to_end_notes_then_nothing_new(tmp_path, monkeypatch):
    feed = {"https://example.com/feed.xml": RSS, "https://example.com/ep12.vtt": VTT.encode()}
    monkeypatch.setattr(RSSSource, "fetch_url", lambda self, url: feed[url])
    cfg = deep_merge(DEFAULTS, {
        "vault_path": str(tmp_path / "vault"), "state_dir": str(tmp_path / "state"),
        "llm": {"backend": "regex"},
        "sources": {"local": {"enabled": False},
                    "rss": {"enabled": True, "urls": ["https://example.com/feed.xml"]}},
    })
    first = run_pipeline(cfg, today=date(2026, 1, 7))
    assert first.processed == 2 and not first.errors
    assert len(list((tmp_path / "vault" / "Sources").glob("*.md"))) == 2
    for n in (tmp_path / "vault").rglob("*.md"):
        assert_note_contract(n)
    assert_links_resolve(tmp_path / "vault")
    second = run_pipeline(cfg, today=date(2026, 1, 8))
    assert second.collected == 0 and second.processed == 0
