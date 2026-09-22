import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { loadConfig, parseFrontmatter, safeNotePath } from '../lib.mjs';
import { writeNote, appendNote, journal, inbox, consolidate } from '../vault-writer.mjs';
import { audit } from '../audit.mjs';
import { fixLinks } from '../fix-links.mjs';
import { normalizeVault } from '../normalize.mjs';
import { backup } from '../backup.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, 'fixtures', 'sample-vault');
const WRITER = path.join(here, '..', 'vault-writer.mjs');

const tmp = [];
after(() => { for (const d of tmp) fs.rmSync(d, { recursive: true, force: true }); });

function tmpVault() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nightshift-vault-'));
  tmp.push(dir);
  fs.cpSync(FIXTURE, dir, { recursive: true });
  return dir;
}
function snapshot(dir) {
  const out = {};
  const rec = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? rec(p) : (out[path.relative(dir, p)] = fs.readFileSync(p, 'utf8')); } };
  rec(dir);
  return out;
}

test('writer creates contract frontmatter and H1 per PARA folder', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const fp = writeNote(v, cfg, '3 - Resources', 'Spaced Repetition', 'Review at growing intervals.');
  const txt = fs.readFileSync(fp, 'utf8');
  const fm = parseFrontmatter(txt);
  assert.deepEqual(fm.fields.tags, ['resource']);
  assert.ok(!fm.flow.has('tags'), 'tags must be a block list');
  assert.match(fm.fields.created, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(fm.fields.updated, fm.fields.created);
  assert.match(fm.body, /^# Spaced Repetition$/m);

  const pj = parseFrontmatter(fs.readFileSync(writeNote(v, cfg, '1 - Projects', 'Launch', 'Ship it.'), 'utf8'));
  assert.deepEqual(pj.fields.tags, ['project']);
  assert.equal(pj.fields.status, 'active');
  assert.ok('deadline' in pj.fields);
});

test('writer keeps caller frontmatter, append bumps updated, journal and inbox follow the contract', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const fp = writeNote(v, cfg, '2 - Areas', 'Finances', '---\ntags:\n  - money\ncreated: 2020-01-01\nupdated: 2020-01-01\n---\n\n# Finances\n');
  appendNote(v, cfg, '2 - Areas', 'Finances', 'New line');
  const txt = fs.readFileSync(fp, 'utf8');
  assert.match(txt, /created: 2020-01-01/);
  assert.doesNotMatch(txt, /updated: 2020-01-01/);
  assert.match(txt, /New line\n$/);

  const j = journal(v, cfg, 'Did things', '2026-02-01');
  assert.match(fs.readFileSync(j, 'utf8'), /^# 2026-02-01$/m);
  journal(v, cfg, 'More things', '2026-02-01');
  assert.match(fs.readFileSync(j, 'utf8'), /More things/);

  const i = inbox(v, cfg, 'A: quick/thought', 'x');
  assert.equal(path.dirname(i), path.join(v, '0 - Inbox'));
  assert.equal(path.basename(i), 'A- quick-thought.md');

  const res = consolidate(v, cfg, [{ folder: '3 - Resources', filename: 'Batch A', content: 'a' }, { folder: '../outside', filename: 'x', content: 'bad' }]);
  assert.equal(res[0].status, 'ok');
  assert.equal(res[1].status, 'error');
});

test('path traversal, root writes and Templates are rejected', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  for (const [folder, file] of [['..', 'escape'], ['../..', 'x'], ['3 - Resources/../../..', 'x'], [path.resolve(os.tmpdir()), 'abs'], ['', 'root'], ['.', 'root'], ['Templates', 'x'], ['.obsidian', 'x']]) {
    assert.throws(() => safeNotePath(v, folder, file, cfg), undefined, `${folder}/${file} should be refused`);
  }
  // A filename cannot smuggle directories.
  const fp = safeNotePath(v, '3 - Resources', '../../evil', cfg);
  assert.equal(path.dirname(fp), path.join(v, '3 - Resources'));
  // Through the CLI: non-zero exit, nothing written outside the vault.
  const r = spawnSync(process.execPath, [WRITER, 'write', '../../', 'pwned', 'x', '--vault', v], { encoding: 'utf8' });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /refused/i);
  assert.ok(!fs.existsSync(path.join(v, '..', '..', 'pwned.md')));
});

test('writer CLI --help works and write goes through the contract', () => {
  assert.match(execFileSync(process.execPath, [WRITER, '--help'], { encoding: 'utf8' }), /Usage: node vault-writer\.mjs/);
  const v = tmpVault();
  execFileSync(process.execPath, [WRITER, 'write', '3 - Resources', 'CLI Note', 'hello', '--vault', v], { encoding: 'utf8' });
  assert.match(fs.readFileSync(path.join(v, '3 - Resources', 'CLI Note.md'), 'utf8'), /^---\ntags:\n  - resource\n/);
});

test('audit finds every seeded violation', () => {
  const cfg = loadConfig(FIXTURE);
  const r = audit(FIXTURE, cfg, { now: Date.parse('2026-01-12') });
  const has = (rule, file) => r.issues.some(i => i.rule === rule && i.file === file);
  assert.ok(has('no-frontmatter', '2 - Areas/Health.md'));
  assert.ok(has('tags-not-list', '3 - Resources/Messy Note.md'));
  assert.ok(has('updated-missing', '3 - Resources/Messy Note.md'));
  assert.ok(has('h1-mismatch', '3 - Resources/Messy Note.md'));
  assert.ok(has('root-note', 'Stray.md'));
  assert.ok(has('project-status-missing', '1 - Projects/Old Project.md'));
  assert.ok(has('orphan', '2 - Areas/Health.md'));
  assert.ok(has('inbox-stale', '0 - Inbox/Quick Idea.md'));
  assert.ok(has('inbox-leftover', '0 - Inbox/Compost 101.md'));
  const broken = r.issues.filter(i => i.rule === 'broken-link').map(i => i.detail);
  assert.equal(broken.length, 2);
  assert.ok(broken.some(d => d.includes('[[Missing Note]]')));
  assert.ok(broken.some(d => d.includes('did you mean [[Composting Basics]]')));
  assert.ok(!broken.some(d => d.includes('in code')), 'links in code spans are ignored');
  assert.ok(!r.issues.some(i => i.file.startsWith('Templates/')), 'templates are skipped');
  assert.ok(!r.issues.some(i => i.file === '1 - Projects/Garden Planner.md'), 'clean note has no issue');
  assert.ok(audit(FIXTURE, cfg, { inboxMax: 1 }).issues.some(i => i.rule === 'inbox-overflow'));
});

test('audit CLI --strict exits non-zero on violations, --json is parseable', () => {
  const r = spawnSync(process.execPath, [path.join(here, '..', 'audit.mjs'), '--vault', FIXTURE, '--strict', '--json'], { encoding: 'utf8' });
  assert.equal(r.status, 1);
  assert.ok(JSON.parse(r.stdout).summary.errors > 0);
  const ok = spawnSync(process.execPath, [path.join(here, '..', 'audit.mjs'), '--vault', FIXTURE], { encoding: 'utf8' });
  assert.equal(ok.status, 0);
});

test('fix-links dry-run writes nothing; --apply repairs case and alias links', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const before = snapshot(v);
  const dry = fixLinks(v, cfg);
  assert.ok(dry.changed >= 1);
  assert.deepEqual(snapshot(v), before, 'dry-run must not touch any file');
  const cli = spawnSync(process.execPath, [path.join(here, '..', 'fix-links.mjs'), '--vault', v], { encoding: 'utf8' });
  assert.match(cli.stdout, /DRY-RUN/);
  assert.deepEqual(snapshot(v), before, 'CLI default must not touch any file');

  fixLinks(v, cfg, { apply: true });
  const messy = fs.readFileSync(path.join(v, '3 - Resources', 'Messy Note.md'), 'utf8');
  assert.match(messy, /\[\[Composting Basics\]\]/);
  assert.match(messy, /\[\[Missing Note\]\]/, 'unresolved links are kept by default');
  assert.match(messy, /`\[\[in code\]\]`/);
});

test('normalize is dry-run by default and --apply satisfies the contract', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const before = snapshot(v);
  const dry = normalizeVault(v, cfg);
  assert.ok(dry.changed > 0);
  assert.deepEqual(snapshot(v), before);
  normalizeVault(v, cfg, { apply: true });
  const messy = parseFrontmatter(fs.readFileSync(path.join(v, '3 - Resources', 'Messy Note.md'), 'utf8'));
  assert.deepEqual(messy.fields.tags, ['resource', 'draft']);
  assert.ok(messy.fields.updated);
  assert.deepEqual(messy.fields.aliases, ['An Old Title']);
  assert.match(messy.body, /^# Messy Note$/m);
  const rules = new Set(audit(v, cfg, { now: Date.parse('2026-01-12') }).issues.map(i => i.rule));
  for (const r of ['no-frontmatter', 'tags-not-list', 'updated-missing', 'h1-mismatch', 'project-status-missing']) assert.ok(!rules.has(r), r);
});

test('backup skips cleanly outside a git repo and when the maintenance lock exists', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const calls = [];
  assert.equal(backup(v, cfg, { git: (...a) => calls.push(a), log: () => {} }).status, 'skipped-not-git');
  fs.mkdirSync(path.join(v, '.git'));
  fs.mkdirSync(path.join(v, '.nightshift'), { recursive: true });
  fs.writeFileSync(path.join(v, cfg.maintenanceLock), '');
  assert.equal(backup(v, cfg, { git: (...a) => calls.push(a), log: () => {} }).status, 'skipped-locked');
  assert.equal(calls.length, 0);
});
