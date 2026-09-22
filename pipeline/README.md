# nightshift pipeline

The Python half of nightshift: it pulls in videos and transcripts, extracts the
useful parts (tools, prompts, techniques, ideas), scores them, and writes linked
Markdown notes into your vault while you sleep.

## Install

```bash
cd pipeline
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"            # core + tests
pip install -e ".[youtube]"        # optional: YouTube source (yt-dlp)
pip install -e ".[whisper]"        # optional: transcribe audio/video (needs ffmpeg)
```

Python 3.10+. The only required dependency is PyYAML.

## Try it offline

```bash
nightshift demo                   # writes ./demo-vault from the samples in examples/
```

No network, no API key, no model: the demo uses the deterministic regex
extractor and finishes in a few seconds.

## Use it

```bash
cp config.example.yaml nightshift.yaml
cp profile.example.yaml profile.yaml   # describe your interests, skills, constraints
nightshift health                      # check vault, optional deps, LLM backend
nightshift run --dry-run               # see what would happen
nightshift run                         # for real
nightshift run --sources local --limit 5
```

Set the vault with `vault_path` in the config or the `NIGHTSHIFT_VAULT`
environment variable. Drop `.txt`, `.md`, `.vtt`, `.srt` (or audio/video with
Whisper installed) into the local drop folder, and/or list YouTube channels and
playlists.

## Stages

1. **collect**: sources yield new items; processed IDs are remembered in a state file
2. **transcribe**: audio/video goes through Whisper if installed, otherwise it is skipped with a log line
3. **classify**: topic categories by keyword density
4. **extract**: tools, prompts, techniques, ideas, summary. Backend chain: `claude -p` CLI, then the Anthropic API (`ANTHROPIC_API_KEY`, model `claude-sonnet-5` by default), then the regex extractor. After 5 consecutive LLM failures a circuit breaker switches the rest of the run to regex.
5. **score**: 0-100 signal score (density, concrete tools, linked repos, cross-creator recurrence, minus engagement bait)
6. **fit**: every idea is scored 0-100 against your `profile.yaml`, with reasons
7. **write**: `Sources/`, `Tools/`, `Ideas/` notes
8. **link**: a "Related" section per source note
9. **digest**: `Digest/Digest YYYY-MM-DD.md`

## Note contract

Every note has YAML frontmatter with `tags` (block list), `created`, `updated`,
`type`, `source` and `score`. The H1 is exactly the file name. Wikilinks only
point to notes that exist. Writes are atomic, file names are sanitised
(no `..`, no separators, no reserved Windows names), and one bad item never
aborts a run.

## Adding a source

Subclass `nightshift.sources.Source`, set `name`, implement
`fetch(limit)` to yield `Item`s, skip IDs where `self.state.is_done(...)`, and
register it with `nightshift.sources.register_source`. Its config lives under
`sources.<name>`.

## Tests

```bash
pytest -q
```

No network and no LLM calls: the tests hide `ANTHROPIC_API_KEY` and the `claude` CLI.
