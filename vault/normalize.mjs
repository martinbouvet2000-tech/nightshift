#!/usr/bin/env node
// normalize.mjs — bring every note in line with the data contract. DRY-RUN BY DEFAULT: --apply to write.
//  - frontmatter added when missing (folder tag, created = birthtime, updated = mtime)
//  - tags: flow list "[a, b]" -> YAML block list
//  - created / updated added when missing
//  - H1 = filename (old H1 kept in `aliases`), skipped for journal, root, README and generatedNotes
// Line endings of each file are preserved. Nothing is ever deleted.
import fs from 'node:fs';
import path from 'node:path';
import { parseArgs, resolveVault, loadConfig, walk, roleOf, isGenerated, atomicWrite, localDate, isMain } from './lib.mjs';

const HELP = `normalize — enforce the data contract on every note (dry-run by default)

Usage: node normalize.mjs [--vault <path>] [--apply] [--json]`;

const normKey = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim().toLowerCase();
const stripEmoji = s => s.replace(/[\p{Extended_Pictographic}️‍]/gu, '').replace(/\s+/g, ' ').trim();
const yq = s => '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';

export function normalizeNote(raw, { rel, config, birth, mtime }) {
  const stats = [];
  const name = path.basename(rel, '.md');
  const role = roleOf(rel, config);
  const eol = raw.includes('\r\n') ? '\r\n' : '\n';
  let txt = raw.replace(/^﻿/, '').replace(/\r\n/g, '\n');
  const before = txt;

  let fmM = txt.match(/^---\n([\s\S]*?)\n---[ \t]*\n?/);
  if (!fmM) {
    const tag = config.folderTags[role] || 'note';
    txt = `---\ntags:\n  - ${tag}\ncreated: ${birth}\nupdated: ${mtime}\n---\n\n` + txt.replace(/^\s+/, '');
    stats.push('frontmatter-added');
    fmM = txt.match(/^---\n([\s\S]*?)\n---[ \t]*\n?/);
  }
  let fm = fmM[1];
  fm = fm.replace(/^tags:\s*\[([^\]]*)\]\s*$/m, (m, inner) => {
    const tags = inner.split(',').map(t => t.trim().replace(/^["']|["']$/g, '').replace(/^#/, '')).filter(Boolean);
    stats.push('tags-listed');
    return 'tags:' + (tags.length ? '\n' + tags.map(t => `  - ${t}`).join('\n') : '');
  });
  if (!/^tags:/m.test(fm)) { fm = `tags:\n  - ${config.folderTags[role] || 'note'}\n` + fm; stats.push('tags-added'); }
  if (!/^created:/m.test(fm)) { fm += `\ncreated: ${birth}`; stats.push('created-added'); }
  if (!/^updated:/m.test(fm)) {
    fm = /^created:.*$/m.test(fm) ? fm.replace(/^(created:.*)$/m, `$1\nupdated: ${mtime}`) : fm + `\nupdated: ${mtime}`;
    stats.push('updated-added');
  }
  if (role === 'projects') {
    if (!/^status:/m.test(fm)) { fm += '\nstatus: active'; stats.push('status-added'); }
    if (!/^deadline:/m.test(fm)) { fm += '\ndeadline:'; stats.push('deadline-added'); }
  }

  let body = txt.slice(fmM[0].length);
  if (role !== 'journal' && role !== 'root' && name.toUpperCase() !== 'README' && !isGenerated(rel, config)) {
    const h1M = body.match(/^# (.+)$/m);
    if (!h1M) {
      body = `# ${name}\n\n` + body.replace(/^\n+/, '');
      stats.push('h1-inserted');
    } else if (h1M[1].trim() !== name) {
      const old = stripEmoji(h1M[1].trim());
      if (normKey(old) !== normKey(name) && old && !fm.includes(old)) {
        if (/^aliases:\s*$/m.test(fm)) fm = fm.replace(/^(aliases:\s*\n(?:\s+-.*\n?)*)/m, m => m.replace(/\n?$/, '') + `\n  - ${yq(old)}\n`);
        else if (/^aliases:\s*\[/m.test(fm)) fm = fm.replace(/^aliases:\s*\[(.*)\]\s*$/m, (m, inner) => `aliases: [${inner ? inner + ', ' : ''}${yq(old)}]`);
        else fm += `\naliases:\n  - ${yq(old)}`;
        stats.push('alias-added');
      }
      body = body.replace(h1M[0], `# ${name}`);
      stats.push('h1-aligned');
    }
  }
  fm = fm.replace(/\n{2,}/g, '\n').replace(/^\n+|\n+$/g, '');
  txt = `---\n${fm}\n---\n` + (body.startsWith('\n') ? '' : '\n') + body;
  return { out: txt === before ? raw : txt.replace(/\n/g, eol), changed: txt !== before, stats };
}

export function normalizeVault(vault, config, { apply = false } = {}) {
  const report = { apply, changed: 0, files: [], totals: {} };
  for (const n of walk(vault, config)) {
    if (n.rel === config.indexFile) continue;
    const st = fs.statSync(n.abs);
    const birth = localDate(st.birthtime && st.birthtime.getTime() > 0 ? st.birthtime : st.mtime);
    const mtime = localDate(st.mtime);
    const raw = fs.readFileSync(n.abs, 'utf8');
    const r = normalizeNote(raw, { rel: n.rel, config, birth, mtime });
    if (!r.changed) continue;
    report.changed++;
    report.files.push({ file: n.rel, fixes: r.stats });
    for (const s of r.stats) report.totals[s] = (report.totals[s] || 0) + 1;
    if (apply) atomicWrite(n.abs, r.out);
  }
  return report;
}

function main(argv) {
  const { flags } = parseArgs(argv, ['apply', 'json', 'help', 'dry-run']);
  if (flags.help) { console.log(HELP); return 0; }
  const vault = resolveVault(flags);
  const config = loadConfig(vault, flags);
  const apply = flags.apply === true && !flags['dry-run'];
  const r = normalizeVault(vault, config, { apply });
  if (flags.json) { console.log(JSON.stringify(r, null, 2)); return 0; }
  for (const f of r.files) console.log(`${f.file}: ${f.fixes.join(', ')}`);
  console.log(`\ntotals ${JSON.stringify(r.totals)}`);
  console.log(`${r.changed} file(s) ${apply ? 'written' : 'would change — DRY-RUN, nothing written (use --apply)'}`);
  return 0;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 1; }
}
