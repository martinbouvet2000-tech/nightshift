# Contributing to nightshift

Thanks for taking the time. nightshift is small on purpose: a Python pipeline, a set of
zero-dependency Node tools, and a night runner. Anything that keeps it small and honest is welcome.

The single most useful contribution right now is **a new `Source`** — podcasts, RSS, a read-later
export. There is a walkthrough at the bottom of this file.

## Ground rules

- Open an issue before a large change, so we don't both build the same thing.
- Every change ships with a test. Both halves have fast, offline, deterministic suites — keep them
  that way: no network, no API key, no wall-clock sleeps in tests.
- Respect [`vault/CONTRACT.md`](vault/CONTRACT.md). Anything that writes a note must produce
  `tags` as a YAML list, `created` and `updated`, an H1 equal to the filename, and no links to
  notes that don't exist.
- Don't add a runtime dependency without a reason in the PR description. `vault/` and `nightly/`
  are dependency-free Node, and the pipeline's only required dependency is PyYAML.
- Treat transcripts as untrusted input (see [Threat model](README.md#threat-model)).

## Dev setup

You need **Python 3.10+** and **Node 18+**. The two halves are independent; you can work on one
without setting up the other.

### Python half (`pipeline/`)

```bash
cd pipeline
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest -q                        # the suite
nightshift demo                  # end-to-end offline run into ./demo-vault
nightshift health                # checks config, vault path, optional extras
```

Optional extras, only needed if you touch those code paths:
`pip install -e ".[youtube]"` (yt-dlp) and `pip install -e ".[whisper]"` (local transcription).

### Node half (`vault/` and `nightly/`)

No install step, no `package.json`, no `node_modules`.

```bash
node --test vault/test/*.test.mjs nightly/test/*.test.mjs
```

Useful while developing:

```bash
node vault/audit.mjs   --vault pipeline/demo-vault --strict   # contract check, exits non-zero
node vault/normalize.mjs --vault <vault>                      # dry-run by default, --apply to write
node nightly/runner.mjs --vault <vault> --dry-run             # prints the exact claude command
```

### Run everything, like CI does

```bash
cd pipeline && pytest -q && nightshift demo && cd ..
node --test vault/test/*.test.mjs nightly/test/*.test.mjs
```

CI runs both suites on ubuntu-latest and windows-latest. If your change touches paths, filenames or
line endings, assume Windows will disagree with you and test there (or watch the CI matrix).

## Commits and pull requests

- Conventional-ish commit subjects (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`) in the
  imperative mood.
- One logical change per PR.
- Fill in the PR template: what changed, how you verified it, and which suites you ran.
- Update `CHANGELOG.md` under `## [Unreleased]` for anything user-visible.

## Adding a new `Source`

A source is a class that yields `Item` objects. It does **not** transcribe, classify, score or
write notes — the pipeline does that. Your job is: produce items, skip what's already done, and
never raise for a single bad entry.

This is the real interface (`pipeline/src/nightshift/sources/base.py`):

```python
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
```

A minimal implementation, `pipeline/src/nightshift/sources/rss.py`:

```python
from __future__ import annotations

import logging
from collections.abc import Iterator

from nightshift.models import Item
from nightshift.sources.base import Source

log = logging.getLogger(__name__)


class RSSSource(Source):
    name = "rss"

    def fetch(self, limit: int | None = None) -> Iterator[Item]:
        count = 0
        for feed_url in self.cfg.get("feeds", []):
            for entry in self._entries(feed_url):          # your parsing, your error handling
                if limit is not None and count >= limit:
                    return
                item_id = f"rss-{entry['guid']}"
                if self.state.is_done(self.name, item_id):  # never reprocess
                    continue
                try:
                    item = Item(
                        id=item_id,
                        source=self.name,
                        title=entry["title"],
                        url=entry["link"],
                        published=entry["date"][:10],       # ISO YYYY-MM-DD
                        transcript=entry["text"],           # or set media_path=... instead
                    )
                except Exception as exc:                    # one bad entry never aborts a run
                    log.warning("skipping %s: %s", item_id, exc)
                    continue
                count += 1
                yield item
```

Then register it in `pipeline/src/nightshift/sources/__init__.py`:

```python
from nightshift.sources.rss import RSSSource

SOURCES: dict[str, type[Source]] = {
    LocalSource.name: LocalSource,
    YouTubeSource.name: YouTubeSource,
    RSSSource.name: RSSSource,
}
```

Out-of-tree sources don't need to edit that file — call `register_source(RSSSource)` instead.

Checklist for the PR:

- [ ] `id` is stable across runs (a content hash or the feed's GUID — not a timestamp or an index).
- [ ] `state.is_done()` is honoured, so a second run is a no-op.
- [ ] A broken entry logs a warning and continues; `fetch` never raises for one item.
- [ ] Either `transcript` or `media_path` is set on every yielded item.
- [ ] Config lives under the source's own key in `config.example.yaml`, documented there.
- [ ] Any new network dependency is an optional extra in `pyproject.toml`, like `youtube` and
      `whisper`, and the source degrades with a clear log line when it isn't installed.
- [ ] Tests in `pipeline/tests/test_sources.py` with the network mocked — see the existing ones.

## Reporting bugs and asking for features

Use the issue templates: [bug report](.github/ISSUE_TEMPLATE/bug_report.yml),
[feature request](.github/ISSUE_TEMPLATE/feature_request.yml),
[new source](.github/ISSUE_TEMPLATE/new_source.yml). Security problems go to
[SECURITY.md](SECURITY.md), not to a public issue.

By contributing you agree that your work is licensed under the [MIT License](LICENSE), and that you
will follow the [Code of Conduct](CODE_OF_CONDUCT.md).
