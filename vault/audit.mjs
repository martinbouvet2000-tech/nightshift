#!/usr/bin/env node
// audit.mjs — read-only health check of a PARA vault against the data contract (CONTRACT.md).
// Reports frontmatter violations, H1 != filename, broken wikilinks, orphans, root strays,
// inbox overflow / stale inbox items, and inbox leftovers already filed elsewhere.
import fs from 'node:fs';
import path from 'node:path';
import {
  parseArgs, resolveVault, loadConfig, parseFrontmatter, extractLinks, firstH1, roleOf,
  buildResolver, isGenerated, fold, isMain,
} from './lib.mjs';

const HELP = `audit — read-only vault health check

Usage: node audit.mjs [--vault <path>] [--config <file>] [--json] [--strict] [--inbox-max N] [--limit N]

  --json        machine-readable output
  --strict      exit 1 when any error-level violation is found (warnings never fail)
  --inbox-max   override config.inboxMax
  --limit       max issues printed per rule in text mode (default 20)`;

const ERROR_RULES = new Set([
  'no-frontmatter', 'tags-missing', 'tags-not-list', 'created-missing', 'updated-missing',
  'h1-mismatch', 'broken-link', 'root-note', 'project-status-missing', 'project-deadline-missing', 'inbox-overflow',
]);

export function audit(vault, config, { inboxMax = config.inboxMax, now = Date.now() } = {}) {
  const resolver = buildResolver(vault, config);
  const issues = [];
  const add = (rule, file, detail = '') => issues.push({ rule, severity: ERROR_RULES.has(rule) ? 'error' : 'warning', file, detail });
  const inbound = new Map();
  const counts = { notes: 0, links: 0, byFolder: {} };

  for (const n of resolver.notes) {
    if (n.rel === config.indexFile) continue;
    counts.notes++;
    const top = n.rel.includes('/') ? n.rel.split('/')[0] : '(root)';
    counts.byFolder[top] = (counts.byFolder[top] || 0) + 1;
    const txt = fs.readFileSync(n.abs, 'utf8');
    const name = path.basename(n.rel, '.md');
    const role = roleOf(n.rel, config);
    const fm = parseFrontmatter(txt);

    if (role === 'root' && !config.rootAllowed.includes(path.basename(n.rel))) add('root-note', n.rel, 'notes must live in a PARA folder');
    if (!fm.present) add('no-frontmatter', n.rel);
    else {
      if (!('tags' in fm.fields)) add('tags-missing', n.rel);
      else if (fm.flow.has('tags') || !Array.isArray(fm.fields.tags)) add('tags-not-list', n.rel, 'use a YAML block list');
      if (!fm.fields.created) add('created-missing', n.rel);
      if (!fm.fields.updated) add('updated-missing', n.rel);
      if (role === 'projects') {
        if (!('status' in fm.fields)) add('project-status-missing', n.rel);
        if (!('deadline' in fm.fields)) add('project-deadline-missing', n.rel);
      }
    }
    const isReadme = name.toUpperCase() === 'README';
    if (role !== 'journal' && role !== 'root' && !isReadme && !isGenerated(n.rel, config)) {
      const h1 = firstH1(fm.body);
      if (h1 !== name) add('h1-mismatch', n.rel, h1 === null ? 'no H1' : `H1 "${h1}"`);
    }
    for (const l of extractLinks(txt)) {
      counts.links++;
      if (!l.target) { add('broken-link', n.rel, 'empty [[]]'); continue; }
      const hit = resolver.resolve(l.target);
      if (hit) { if (hit !== name) inbound.set(hit, (inbound.get(hit) || 0) + 1); continue; }
      const s = resolver.suggest(l.target);
      add('broken-link', n.rel, `[[${l.target}]]${s ? ` (did you mean [[${s}]]?)` : ''}`);
    }
  }

  // Orphans: no inbound link from any other note (journal, root and index notes exempt).
  for (const n of resolver.notes) {
    const role = roleOf(n.rel, config);
    if (n.rel === config.indexFile || role === 'journal' || role === 'root') continue;
    if (!inbound.has(path.basename(n.rel, '.md'))) add('orphan', n.rel);
  }

  // Inbox: overflow, stale items, leftovers already filed elsewhere (name = alias of another note).
  const inbox = resolver.notes.filter(n => roleOf(n.rel, config) === 'inbox');
  if (inbox.length > inboxMax) add('inbox-overflow', config.folders.inbox, `${inbox.length} items > ${inboxMax}`);
  const aliasFolded = new Map(resolver.allAliases.filter(([, t]) => resolver.names.get(t) && roleOf(resolver.names.get(t), config) !== 'inbox').map(([a, t]) => [fold(a), t]));
  for (const n of inbox) {
    const txt = fs.readFileSync(n.abs, 'utf8');
    const created = parseFrontmatter(txt).fields.created;
    const t = created ? Date.parse(created) : fs.statSync(n.abs).mtimeMs;
    const age = Math.floor((now - t) / 86400000);
    if (Number.isFinite(age) && age > config.inboxMaxAgeDays) add('inbox-stale', n.rel, `${age} days old`);
    const filed = aliasFolded.get(fold(path.basename(n.rel, '.md')));
    if (filed) add('inbox-leftover', n.rel, `already filed as [[${filed}]]`);
  }

  const summary = { ...counts, errors: issues.filter(i => i.severity === 'error').length, warnings: issues.filter(i => i.severity === 'warning').length, byRule: {} };
  for (const i of issues) summary.byRule[i.rule] = (summary.byRule[i.rule] || 0) + 1;
  summary.orphans = summary.byRule.orphan || 0;
  summary.brokenLinks = summary.byRule['broken-link'] || 0;
  summary.linksPerNote = counts.notes ? +(counts.links / counts.notes).toFixed(2) : 0;
  return { vault, summary, issues };
}

function printText(res, limit) {
  const s = res.summary;
  console.log(`notes ${s.notes} · links ${s.links} (${s.linksPerNote}/note) · errors ${s.errors} · warnings ${s.warnings}`);
  console.log(`folders ${JSON.stringify(s.byFolder)}`);
  const byRule = new Map();
  for (const i of res.issues) byRule.set(i.rule, [...(byRule.get(i.rule) || []), i]);
  for (const [rule, list] of byRule) {
    console.log(`\n[${list[0].severity}] ${rule} (${list.length})`);
    for (const i of list.slice(0, limit)) console.log(`  ${i.file}${i.detail ? ' — ' + i.detail : ''}`);
    if (list.length > limit) console.log(`  … ${list.length - limit} more`);
  }
  if (!res.issues.length) console.log('\nclean: no violations');
}

function main(argv) {
  const { flags } = parseArgs(argv, ['json', 'strict', 'help']);
  if (flags.help) { console.log(HELP); return 0; }
  const vault = resolveVault(flags);
  const config = loadConfig(vault, flags);
  const res = audit(vault, config, { inboxMax: flags['inbox-max'] !== undefined ? Number(flags['inbox-max']) : config.inboxMax });
  if (flags.json) console.log(JSON.stringify(res, null, 2));
  else printText(res, flags.limit ? Number(flags.limit) : 20);
  return flags.strict && res.summary.errors > 0 ? 1 : 0;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 2; }
}
