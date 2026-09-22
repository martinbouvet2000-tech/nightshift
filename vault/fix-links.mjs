#!/usr/bin/env node
// fix-links.mjs — repair broken [[wikilinks]]. DRY-RUN BY DEFAULT: pass --apply to write.
// Strategies, in order: empty link removal, path/.md normalisation, alias -> real name,
// explicit --map, unique case/accent-insensitive match. Unresolved links are kept unless
// --unresolved=plain|code. Code spans and fenced blocks are never touched.
import fs from 'node:fs';
import path from 'node:path';
import { parseArgs, resolveVault, loadConfig, buildResolver, linkTarget, atomicWrite, isMain } from './lib.mjs';

const HELP = `fix-links — repair broken wikilinks (dry-run by default)

Usage: node fix-links.mjs [--vault <path>] [--apply] [--map map.json] [--unresolved keep|plain|code] [--json]

  --apply        actually write the changes (otherwise nothing is written)
  --map          JSON object {"Old target": "Existing note"} for explicit remaps
  --unresolved   what to do with links that cannot be resolved: keep (default), plain text, or \`code\``;

const CODE_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;

export function fixText(txt, resolver, { map = {}, unresolved = 'keep' } = {}) {
  const changes = [];
  const leftovers = [];
  const fixSegment = seg => seg.replace(/(!?)\[\[([^\]]*?)\]\]/g, (m, bang, inner) => {
    if (!inner.trim()) { changes.push({ from: m, to: '', why: 'empty' }); return ''; }
    const cut = inner.search(/[|#]/);
    const rawTarget = cut === -1 ? inner : inner.slice(0, cut);
    const tail = cut === -1 ? '' : inner.slice(cut);
    const t = linkTarget(rawTarget);
    const rewrite = (to, why) => { const out = `${bang}[[${to}${tail}]]`; if (out !== m) changes.push({ from: m, to: out, why }); return out; };
    const hit = resolver.resolve(t);
    if (hit) {
      if (hit !== t) return rewrite(hit, 'alias');
      return t !== rawTarget.trim() ? rewrite(t, 'normalised') : m;
    }
    if (map[t] && resolver.resolve(map[t])) return rewrite(resolver.resolve(map[t]), 'map');
    const s = resolver.suggest(t);
    if (s) return rewrite(s, 'case');
    leftovers.push(t);
    if (unresolved === 'plain') { changes.push({ from: m, to: t, why: 'plain' }); return t; }
    if (unresolved === 'code') { changes.push({ from: m, to: '`' + t + '`', why: 'code' }); return '`' + t + '`'; }
    return m;
  });
  const out = txt.split(CODE_RE).map((part, i) => (i % 2 ? part : fixSegment(part))).join('');
  return { out, changes, leftovers };
}

export function fixLinks(vault, config, { apply = false, map = {}, unresolved = 'keep' } = {}) {
  const resolver = buildResolver(vault, config);
  const report = { apply, files: [], leftovers: {}, changed: 0 };
  for (const n of resolver.notes) {
    if (n.rel === config.indexFile) continue;
    const raw = fs.readFileSync(n.abs, 'utf8');
    const { out, changes, leftovers } = fixText(raw, resolver, { map, unresolved });
    for (const l of leftovers) (report.leftovers[l] ||= []).push(n.rel);
    if (out !== raw) {
      report.changed++;
      report.files.push({ file: n.rel, changes });
      if (apply) atomicWrite(n.abs, out);
    }
  }
  return report;
}

function main(argv) {
  const { flags } = parseArgs(argv, ['apply', 'json', 'help', 'dry-run']);
  if (flags.help) { console.log(HELP); return 0; }
  const vault = resolveVault(flags);
  const config = loadConfig(vault, flags);
  const map = typeof flags.map === 'string' ? JSON.parse(fs.readFileSync(path.resolve(flags.map), 'utf8')) : {};
  const unresolved = typeof flags.unresolved === 'string' ? flags.unresolved : 'keep';
  if (!['keep', 'plain', 'code'].includes(unresolved)) throw new Error('--unresolved must be keep, plain or code');
  const apply = flags.apply === true && !flags['dry-run'];
  const r = fixLinks(vault, config, { apply, map, unresolved });
  if (flags.json) { console.log(JSON.stringify(r, null, 2)); return 0; }
  for (const f of r.files) for (const c of f.changes) console.log(`${f.file}: ${c.from} -> ${c.to || '(removed)'} [${c.why}]`);
  const left = Object.entries(r.leftovers);
  if (left.length) { console.log('\nunresolved:'); for (const [t, files] of left) console.log(`  [[${t}]] <- ${[...new Set(files)].join(', ')}`); }
  console.log(`\n${r.changed} file(s) ${apply ? 'written' : 'would change'}${apply ? '' : ' — DRY-RUN, nothing written (use --apply)'}`);
  return 0;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 1; }
}
