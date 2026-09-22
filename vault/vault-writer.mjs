#!/usr/bin/env node
// vault-writer.mjs — single write entry point for an Obsidian-style PARA vault.
// Every write follows the data contract (see CONTRACT.md): YAML tag list, created + updated,
// H1 = filename, atomic writes, no path traversal, never at the vault root or in Templates.
import fs from 'node:fs';
import path from 'node:path';
import {
  parseArgs, resolveVault, loadConfig, safeNotePath, atomicWrite, walk, parseFrontmatter,
  extractLinks, firstH1, roleOf, today, sanitizeFilename, isMain,
} from './lib.mjs';

const HELP = `vault-writer — contract-aware writes for a PARA vault

Usage: node vault-writer.mjs <command> [args] [--vault <path>] [--config <file>]

Commands:
  write <folder> <filename> [content]    Create or replace a note (frontmatter + H1 added if missing)
  append <folder> <filename> [content]   Append to a note (created if missing, 'updated' bumped)
  journal [content] [--date YYYY-MM-DD]  Create or append to the daily journal note
  inbox <title> [content]                Quick capture into the inbox folder
  consolidate <json>                     Batch: [{"folder","filename","content","mode":"write|append"}]
  index                                  Rebuild the index file (default VAULT_INDEX.md)
  tags                                   List all tags with counts

Content is read from stdin when not given as an argument.
Vault path: --vault <path> or the NIGHTSHIFT_VAULT environment variable.
Config: --config <file>, else <vault>/vault.config.json, else built-in defaults.
Options: --no-index (skip the incremental index update), --help`;

// ─── Contract helpers ───────────────────────────────────────────────

function frontmatterFor(role, config, date) {
  const tag = config.folderTags[role] || 'note';
  const extra = role === 'projects' ? 'status: active\ndeadline:\n' : '';
  return `---\ntags:\n  - ${tag}\ncreated: ${date}\nupdated: ${date}\n${extra}---\n\n`;
}

export function applyContract(vault, fp, content, config, date = today()) {
  const rel = path.relative(vault, fp).replace(/\\/g, '/');
  const name = path.basename(fp, '.md');
  let txt = String(content ?? '').replace(/^﻿/, '');
  const fm = parseFrontmatter(txt);
  let body = fm.present ? fm.body : txt;
  if (!firstH1(body) && roleOf(rel, config) !== 'journal') body = `# ${name}\n\n${body.replace(/^\n+/, '')}`;
  if (fm.present) return txt.slice(0, txt.length - fm.body.length) + body;
  return frontmatterFor(roleOf(rel, config), config, date) + body;
}

function bumpUpdated(txt, date) {
  const fm = parseFrontmatter(txt);
  if (!fm.present) return txt;
  const head = txt.slice(0, txt.length - fm.body.length);
  const newHead = /^updated:.*$/m.test(head)
    ? head.replace(/^updated:.*$/m, `updated: ${date}`)
    : head.replace(/^(created:.*)$/m, `$1\nupdated: ${date}`);
  return newHead + fm.body;
}

// ─── Commands ───────────────────────────────────────────────────────

export function writeNote(vault, config, folder, filename, content) {
  const fp = safeNotePath(vault, folder, filename, config);
  if (fs.existsSync(fp)) console.error(`warning: overwriting existing note ${path.relative(vault, fp)}`);
  atomicWrite(fp, applyContract(vault, fp, content, config));
  return fp;
}

export function appendNote(vault, config, folder, filename, content) {
  const fp = safeNotePath(vault, folder, filename, config);
  if (!fs.existsSync(fp)) return writeNote(vault, config, folder, filename, content);
  const existing = fs.readFileSync(fp, 'utf8');
  const eol = existing.includes('\r\n') ? '\r\n' : '\n';
  const add = String(content ?? '').replace(/\r?\n/g, eol);
  atomicWrite(fp, bumpUpdated(existing, today()).replace(/\s*$/, '') + eol + eol + add + eol);
  return fp;
}

export function journal(vault, config, content, date = today()) {
  const fp = safeNotePath(vault, config.folders.journal, date, config);
  if (fs.existsSync(fp)) return appendNote(vault, config, config.folders.journal, date, content);
  const tpl = `---\ntags:\n  - journal\ncreated: ${date}\nupdated: ${date}\n---\n\n# ${date}\n\n## Focus\n-\n\n## Notes\n${content ? content + '\n' : ''}\n## Decisions\n\n## Tomorrow\n-\n`;
  atomicWrite(fp, tpl);
  return fp;
}

export function inbox(vault, config, title, content) {
  const clean = sanitizeFilename(title);
  const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
  const d = today();
  const note = `---\ntags:\n  - ${config.folderTags.inbox || 'inbox'}\ncreated: ${d}\nupdated: ${d}\ncaptured: ${stamp}\n---\n\n# ${clean}\n\n${content || ''}\n`;
  const fp = safeNotePath(vault, config.folders.inbox, clean, config);
  if (fs.existsSync(fp)) console.error(`warning: overwriting existing note ${path.relative(vault, fp)}`);
  atomicWrite(fp, note);
  return fp;
}

export function consolidate(vault, config, notes) {
  if (!Array.isArray(notes)) throw new Error('consolidate expects a JSON array');
  return notes.map(n => {
    const { folder, filename, content, mode = 'write' } = n || {};
    try {
      const fp = mode === 'append' ? appendNote(vault, config, folder, filename, content) : writeNote(vault, config, folder, filename, content);
      return { filename, path: fp, status: 'ok' };
    } catch (e) {
      return { filename, status: 'error', error: e.message };
    }
  });
}

function tagsOf(txt) {
  const fm = parseFrontmatter(txt);
  const set = new Set();
  const t = fm.fields.tags;
  for (const x of Array.isArray(t) ? t : t ? String(t).split(/[,\s]+/) : []) if (x) set.add(x.replace(/^#/, ''));
  for (const m of fm.body.matchAll(/(?:^|\s)#([\p{L}\p{N}_\-/]+)/gu)) if (!/^\d+$/.test(m[1])) set.add(m[1]);
  return [...set];
}

export function buildIndex(vault, config) {
  const files = walk(vault, config).filter(f => f.rel !== config.indexFile);
  const lines = [
    `# Vault Index — ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`,
    `# ${files.length} notes`,
    '# FORMAT: path | para | tags | links | status | modified | words | heading',
  ];
  for (const f of files) {
    try {
      const txt = fs.readFileSync(f.abs, 'utf8');
      const fm = parseFrontmatter(txt);
      const links = [...new Set(extractLinks(txt).map(l => l.target))];
      const words = fm.body.trim() ? fm.body.trim().split(/\s+/).length : 0;
      const mod = fs.statSync(f.abs).mtime.toISOString().slice(0, 10);
      const esc = s => String(s ?? '').replace(/\|/g, '/');
      lines.push([f.rel, f.rel.split('/')[0], tagsOf(txt).join(', '), links.join(', '), fm.fields.status || '', mod, words, (firstH1(fm.body) || '').slice(0, 80)].map(esc).join(' | '));
    } catch (e) {
      console.error(`warning: index skipped ${f.rel}: ${e.message}`);
    }
  }
  atomicWrite(path.join(vault, config.indexFile), lines.join('\n') + '\n');
  return files.length;
}

export function listTags(vault, config) {
  const count = new Map();
  for (const f of walk(vault, config)) for (const t of tagsOf(fs.readFileSync(f.abs, 'utf8'))) count.set(t, (count.get(t) || 0) + 1);
  return [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

// ─── CLI ────────────────────────────────────────────────────────────

function readStdin() {
  if (process.stdin.isTTY) return '';
  try { return fs.readFileSync(0, 'utf8'); } catch { return ''; }
}
const contentOf = rest => (rest.length ? rest.join(' ') : readStdin());

function main(argv) {
  const { positional, flags } = parseArgs(argv, ['help', 'no-index']);
  const [cmd, ...args] = positional;
  if (flags.help || !cmd || cmd === 'help') { console.log(HELP); return cmd || flags.help ? 0 : 1; }
  const vault = resolveVault(flags);
  const config = loadConfig(vault, flags);
  let wrote = false;
  switch (cmd) {
    case 'write': { const [folder, filename, ...rest] = args; console.log(`ok ${writeNote(vault, config, folder, filename, contentOf(rest))}`); wrote = true; break; }
    case 'append': { const [folder, filename, ...rest] = args; console.log(`ok appended ${appendNote(vault, config, folder, filename, contentOf(rest))}`); wrote = true; break; }
    case 'journal': { console.log(`ok journal ${journal(vault, config, contentOf(args), typeof flags.date === 'string' ? flags.date : today())}`); wrote = true; break; }
    case 'inbox': { const [title, ...rest] = args; console.log(`ok inbox ${inbox(vault, config, title, contentOf(rest))}`); wrote = true; break; }
    case 'consolidate': {
      const res = consolidate(vault, config, JSON.parse(contentOf(args)));
      for (const r of res) console.log(`${r.status} ${r.filename}${r.error ? ' — ' + r.error : ''}`);
      wrote = true;
      if (res.some(r => r.status !== 'ok')) process.exitCode = 1;
      break;
    }
    case 'index': console.log(`ok index: ${buildIndex(vault, config)} notes -> ${config.indexFile}`); return 0;
    case 'tags': { const t = listTags(vault, config); console.log(`${t.length} tags`); t.forEach(([k, n]) => console.log(`  ${k} (${n})`)); return 0; }
    default: console.error(`Unknown command: ${cmd}\n\n${HELP}`); return 1;
  }
  if (wrote && !flags['no-index'] && fs.existsSync(path.join(vault, config.indexFile))) buildIndex(vault, config);
  return process.exitCode || 0;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 1; }
}
