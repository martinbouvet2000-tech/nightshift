<!--
Thanks for the PR. Keep it to one logical change, and please fill in the verification section —
"CI is green" is not the same as "I ran it".
-->

## What this changes

<!-- One or two sentences. What was wrong or missing, and what it does now. -->

Closes #

## Area

- [ ] `pipeline/` — Python CLI, sources, extraction, scoring, note writing
- [ ] `vault/` — writer, audit, fix-links, normalize, backup
- [ ] `nightly/` — night runner, prompt, schedulers
- [ ] Docs, examples or CI

## How I verified it

<!-- Paste the actual output, not a claim. -->

```
$ cd pipeline && pytest -q

$ node --test vault/test/*.test.mjs nightly/test/*.test.mjs

$ nightshift demo
```

Manual checks, if any:

<!-- e.g. "ran node vault/audit.mjs --vault pipeline/demo-vault --strict, exit 0" -->

## Checklist

- [ ] Both test suites pass locally, and I added a test for this change.
- [ ] Tests stay offline and deterministic — no network, no API key, no sleeps.
- [ ] No new **required** dependency (an optional extra in `pyproject.toml` is fine, and is
      documented).
- [ ] Anything that writes a note still satisfies `vault/CONTRACT.md`
      (`node vault/audit.mjs --vault <vault> --strict` exits 0).
- [ ] Docs updated (`README.md`, the relevant sub-README, `config.example.yaml`).
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` if this is user-visible.
- [ ] I considered Windows: paths, filenames, line endings.

## Notes for the reviewer

<!-- Trade-offs, things you are unsure about, follow-ups you deliberately left out. -->
