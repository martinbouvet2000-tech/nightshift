# nightshift / vault

Zero-dependency Node (>= 18) tools that keep a Markdown PARA vault (Obsidian-compatible) healthy.
The rules they enforce are in [CONTRACT.md](CONTRACT.md).

```sh
export NIGHTSHIFT_VAULT=~/notes          # or pass --vault <path> to every command
cp vault.config.example.json "$NIGHTSHIFT_VAULT/vault.config.json"   # optional
```

| Script | What it does | Writes? |
|---|---|---|
| `vault-writer.mjs` | `write`, `append`, `journal`, `inbox`, `consolidate`, `index`, `tags`. Adds contract frontmatter and H1, atomic writes, refuses path traversal, the vault root and `Templates/`. | yes |
| `audit.mjs` | Contract violations, H1 ≠ filename, broken links, orphans, root strays, inbox overflow / stale / leftovers. `--json`, `--strict` (exit 1 on errors). | never |
| `fix-links.mjs` | Repairs broken wikilinks (alias, path, case/accent, `--map`). | only with `--apply` |
| `indexes.mjs` | One `Index - <folder>` note per configured folder, newest month first, sorted by a field such as `score`. Every captured note gets a real inbound link, which a Dataview or Bases query does not create. Rewritten only when the listing changes. | only with `--apply` |
| `normalize.mjs` | Tag lists, `created`/`updated`, project fields, H1 = filename (old title → `aliases`). | only with `--apply` |
| `backup.mjs` | `git add -A`, commit, pull --rebase, push. Skips if not a git repo or a maintenance lock exists; never force-pushes. | git only |

```sh
node vault-writer.mjs write "3 - Resources" "Spaced Repetition" "Review at growing intervals."
echo "Shipped the beta." | node vault-writer.mjs journal
node audit.mjs --strict
node fix-links.mjs            # dry-run report
node fix-links.mjs --apply
node indexes.mjs --apply      # Index - Journal, Index - Ideas, Index - Digest
node backup.mjs --reason nightly
```

Tests: `node --test test/` (runs against copies of `test/fixtures/sample-vault`).

Config keys (`vault.config.json`): `folders`, `folderTags`, `ignoreDirs`, `rootAllowed`,
`generatedNotes` (regexes for pipeline-owned notes: H1 exempt, never edited at night), `indexFile`,
`inboxMax`, `inboxMaxAgeDays`, `maintenanceLock`, `indexes` (folders for `indexes.mjs`, e.g.
`[{"folder": "Ideas", "sortBy": "score"}]`; default: the journal, `Ideas` and `Digest` when they exist).
