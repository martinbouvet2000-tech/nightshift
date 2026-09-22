# Porting notes

This package is a generalised port of a private, single-user pipeline
(a PowerShell orchestrator driving ~16 Python stages). What was kept, changed
and dropped:

## Kept (generalised)

| Original stage | nightshift module | Changes |
|---|---|---|
| shared helpers (atomic writes, UTF-8) | `fsutil.py` | temp file in same dir + `os.replace` with retry; added traversal-safe joins and Windows-reserved-name handling |
| YouTube sync | `sources/youtube.py` | yt-dlp Python API instead of subprocess; native subtitles only; retry counter per video |
| local transcription (Whisper) | `sources/local.py`, `transcribe.py` | now a generic drop folder; Whisper is an optional extra |
| keyword categorisation | `classify.py` | English keyword set, word-boundary matching |
| knowledge extraction (LLM + local fallback) | `extract.py`, `llm.py` | same `claude -p` → API → regex chain; English prompt; circuit breaker (5 consecutive failures); regex extractor now also finds prompts, techniques and ideas |
| signal scoring | `scoring.py` | same formula (density, tools, repos, recurrence, hype), plus a small bonus for extracted techniques/prompts |
| opportunity / founder-fit filter | `profile.py` | replaced a hard-coded personal filter with a user-editable profile and deterministic, explainable scoring |
| related-notes linking | `linking.py` | links are only emitted to notes that exist |
| hub / digest | `digest.py` | one idempotent daily digest note |
| health check | `health.py` | environment checks only, no secrets printed |
| orchestrator | `pipeline.py`, `cli.py` | pure Python, per-item error isolation, `--dry-run`, `--limit` |

## Dropped

- Social-network connectors (Instagram, TikTok, Discord): out of scope — they rely on unofficial APIs and session cookies.
- Session-learning / self-improvement loops and the auto-extended tool catalog: tightly coupled to one user's history. Use `extra_tools` in the config instead.
- Web enrichment (GitHub star lookups, web search): needs network access and API tokens; may return as an optional stage.
- LLM "deepen" pass and monthly LLM budget counter: the circuit breaker plus `--limit` cover the safety need for now.
- Design-showcase, comparison, resource and code-pattern knowledge files: too specific to one vault layout; the schema keeps tools, prompts, techniques and ideas.
- Video archival to secondary drives and scheduled-task wiring: the scheduling half lives in `nightly/`.
