# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet. See the [Roadmap](README.md#roadmap) for what is being considered.

## [0.1.0] - 2026-09-22

First public release — the open-source core of a personal system, with the personal parts removed.

### Added

**Pipeline (`pipeline/`, Python 3.10+, PyYAML the only required dependency)**

- `nightshift` CLI with three commands: `run` (the configured sources), `demo` (offline, on four
  bundled sample transcripts) and `health` (checks config, vault path and optional extras).
- Pluggable `Source` interface with a registry and `register_source()` for out-of-tree sources.
  Two implementations ship: `local` (a drop folder of `.txt`/`.md`/`.vtt`/`.srt` and audio/video)
  and `youtube` (channel feeds, subtitles first).
- Persistent per-source `StateStore`, so a second run over the same items is a no-op.
- Transcription stage: existing subtitles when available, otherwise optional local Whisper.
- Three-tier extraction with automatic fallback: the `claude` CLI you already pay for, then the
  Anthropic API when `ANTHROPIC_API_KEY` is set, then a deterministic offline regex extractor. A
  circuit breaker stops calling the model for the rest of the run after 5 consecutive failures.
- Classification, a 0–100 signal score, and idea scoring against a `profile.yaml` you write
  (interests, skills, constraints).
- Contract-safe note writer: atomic writes, filenames sanitised against path traversal and reserved
  names, PARA-aware placement, related-note linking and a daily digest.
- One bad item never aborts a run: it is logged, counted in the summary and skipped.
- Optional extras: `[youtube]` (yt-dlp), `[whisper]` (openai-whisper), `[dev]` (pytest), `[all]`.
- `config.example.yaml` and `profile.example.yaml`, plus `PORTING.md`.
- 70 pytest tests, all offline.

**Vault tools (`vault/`, Node 18+, zero dependencies)**

- `CONTRACT.md`: the data contract every note must satisfy — YAML `tags` as a list, `created` and
  `updated`, an H1 equal to the filename, no links to notes that don't exist.
- `vault-writer.mjs`: contract-aware writer used by both halves, with a CLI.
- `audit.mjs`: contract checker with `--strict` (non-zero exit) and `--json`.
- `fix-links.mjs` and `normalize.mjs`: link repair and note normalisation, dry-run by default,
  `--apply` to write.
- `backup.mjs`: git commit and push of the vault, skipping cleanly outside a git repo or under a
  maintenance lock.
- A sample vault fixture with seeded violations, and 19 `node --test` tests covering the writer,
  the auditor, the fixers, the backup and the night runner.

**Night shift (`nightly/`, Node 18+, zero dependencies)**

- `runner.mjs`: a cross-platform wrapper around `claude -p` with a `--since` work window (at least
  36 h, at most 7 days, so missed nights are caught up), a lock with stale-lock takeover, a
  maintenance-lock skip, an 18-minute timeout that kills the whole process tree, and one retry on
  session-limit or API errors.
- Proof of execution: the agent must end with `NIGHTSHIFT_OK <journal> notes=N links=N proposals=N`.
  When that line is missing, a `## Nightshift — <date>` failure block is appended to the journal, so
  "nothing to do" is never confused with "didn't run".
- `state.json` with run counters and last status, plus per-run logs (last 30 kept).
- `nightly-prompt.md`: the consolidation prompt, rendered with the window, the journal date, the
  notes changed in the window and a fresh audit summary.
- Least privilege: `acceptEdits` mode, no extra tool grants, no shell.
- Scheduler examples for Windows Task Scheduler, cron and launchd.

**Project**

- CI on GitHub Actions: both suites plus the offline demo, on ubuntu-latest and windows-latest.
- MIT license.

### Known limitations

- The offline extractor is heuristic; LLM mode is much sharper.
- YouTube and Whisper are covered by mocked tests only.
- Idea scoring against your profile is keyword-based.
- The night runner is tested with a mocked `claude` call; the real prompt has only run in the
  original personal setup.
- Social-network connectors are not included: they rely on unofficial APIs.

[Unreleased]: https://github.com/martinbouvet2000-tech/nightshift/compare/ac993f1...HEAD
[0.1.0]: https://github.com/martinbouvet2000-tech/nightshift/commit/ac993f1
