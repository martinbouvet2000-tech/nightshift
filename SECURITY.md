# Security Policy

## Supported versions

nightshift is at v0.1. Only `main` is supported; fixes land there and are noted in
[`CHANGELOG.md`](CHANGELOG.md).

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

- Preferred: [open a private security advisory](https://github.com/martinbouvet2000-tech/nightshift/security/advisories/new)
  on GitHub.
- Alternative: open a regular issue **without technical details** and ask for a private channel.

Please include what you can: affected file or command, a minimal reproduction, the impact you
think it has, and your environment (OS, Python and Node versions). A proof-of-concept vault or
transcript is very welcome.

This is a personal project maintained by one person, so no SLA is promised. Realistically: an
acknowledgement within a week, and an assessment with a fix or a documented limitation after that.
You'll be credited in the changelog unless you'd rather not be. Please give a reasonable window
before public disclosure.

## Threat model

This repeats the summary in the [README](README.md#threat-model), which is the authoritative copy.

Transcripts come from the internet, so treat them as untrusted input: a video could contain text
written to steer an AI agent.

- The night agent is granted no extra tools: reads, and writes in `acceptEdits` mode, stay inside
  the vault (Claude Code's working-directory limit), and it has no shell. It can't read your SSH
  keys and paste them into a note that `backup.mjs` would push.
- Notes are written through sanitised filenames and a path join that refuses to leave the vault.
- The API key is read from the environment only, and it's never sent to a non-`https://` base URL.
- Review what the agent changed (`git diff` in your vault) before you rely on it, at least for the
  first nights.

### In scope

- Escaping the vault directory when writing notes (path traversal, symlinks, reserved Windows
  names, absolute paths in a transcript or in config).
- Prompt injection in transcripts that leads to something worse than a bad note — for example
  exfiltration, or a write outside the vault.
- Leaking `ANTHROPIC_API_KEY` or other environment secrets into notes, logs or network requests.
- Sending a key or transcript content to an unintended host, including a downgraded
  (non-`https://`) base URL.
- Command injection in the night runner's invocation of `claude`, the scheduler scripts, or
  `backup.mjs`'s git calls.
- Anything that makes `vault/backup.mjs` commit and push content it shouldn't.

### Out of scope

- Vulnerabilities in Claude Code, the Anthropic API, `yt-dlp`, `openai-whisper`, PyYAML, Node or
  Python themselves — report those upstream.
- The *content quality* of what a model writes into your vault. A misleading note is a bug, not a
  vulnerability. The night agent only makes additive changes and proposes risky ones; reviewing its
  diff is part of the design.
- Anything requiring you to already control the machine, the vault directory, or the config file.
- Running nightshift against a vault you don't trust, or pointing `local.drop_folder` at a folder
  an attacker controls *and* then not reviewing the result.
- Denial of service through an enormous transcript or a huge drop folder.

## Hardening notes for operators

- Keep the vault in its own git repo, and read `git diff` after the first few nights.
- Don't put secrets in the vault. `backup.mjs` pushes what is there.
- `ANTHROPIC_API_KEY` is optional — the pipeline falls back to the `claude` CLI and then to the
  offline extractor. If you don't set it, there's no key to leak.
- `node vault/audit.mjs --vault <vault> --strict` exits non-zero on a contract violation; it is a
  cheap tripwire to run after a night.
