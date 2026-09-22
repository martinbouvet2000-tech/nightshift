# nightshift / nightly

The night shift: a cross-platform Node runner that launches Claude Code headless (`claude -p`) on
your vault every night, consolidates the day into the right notes, adds links, and leaves a report in
the journal. Requires Node >= 18, [Claude Code](https://docs.claude.com/en/docs/claude-code) on the
`PATH`, and the sibling `vault/` folder (the runner reuses its config, audit and writer).

```sh
node runner.mjs --vault ~/notes --dry-run          # show the exact command, call nothing
node runner.mjs --vault ~/notes                    # one real run
node runner.mjs --vault ~/notes --backup           # + git commit/push of the vault afterwards
```

## What the runner guarantees

| Concern | Behaviour |
|---|---|
| Work window | `--since` = last success, at least 36 h, at most 7 days back (missed nights are caught up) |
| Journal date | A run before 06:00 consolidates the previous day |
| Concurrency | `runner.lock` in the state dir; a stale lock (dead pid or too old) is taken over |
| Maintenance | Skips cleanly when `<vault>/.nightshift/maintenance.lock` exists |
| Timeout | 18 min per attempt (`--timeout-min`), whole process tree killed |
| Retry | One retry after 20 min (`--retry-wait-min`) on session-limit or API/network errors |
| Success | Last output line `NIGHTSHIFT_OK <journal> notes=N links=N proposals=N` with the right date, or a report found in the journal |
| Failure | A `## Nightshift — <date>` block with the reason is appended to the journal note, so "did not run" is never silent |
| State | `state.json`: `last_success`, `journal`, `run_id`, `model`, `notes`, `links`, `proposals`, `runs_total`, `failures_total`, `consecutive_failures`, `last_status` |
| Logs | `logs/run_<id>.log` + raw agent output, last 30 runs kept |

The prompt (`nightly-prompt.md`) is rendered with the window, the journal date, the list of notes
changed in the window and a fresh `vault/audit.mjs` summary, then piped to `claude -p` on stdin.
The agent gets no extra tool permissions: file reads and `acceptEdits` writes stay inside the vault (Claude Code's working-directory limit), and it has no shell access
(`--permission-mode acceptEdits`). It executes safe additive actions and only *proposes* moves,
renames, merges and deletions.

## Options and environment

| Flag | Env | Default |
|---|---|---|
| `--vault` | `NIGHTSHIFT_VAULT` | required |
| `--state-dir` | `NIGHTSHIFT_STATE_DIR` | `~/.nightshift/nightly` |
| `--model` | `NIGHTSHIFT_MODEL` | `claude-sonnet-5` |
| `--claude` | `NIGHTSHIFT_CLAUDE` | `claude` |
| `--prompt`, `--timeout-min`, `--retry-wait-min`, `--allowed-tools`, `--permission-mode`, `--journal`, `--backup`, `--dry-run`, `--print-prompt` | | see `--help` |

## Scheduling

- Windows: `schedule/register-windows-task.ps1 -Vault "D:\notes" -Time 05:30` (wake-to-run, catch-up, 1 h limit)
- Linux/macOS cron: `schedule/crontab.example`
- macOS launchd: `schedule/com.nightshift.nightly.plist`

05:30 is a good default: the machine is more likely to be on than at midnight, and the journal-date
rule still targets the day that just ended.

Tests: `node --test test/` (the claude call is injected; nothing real is spawned except `node`).
