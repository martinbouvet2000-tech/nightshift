// Shared helpers for the nightshift vault tools. Zero dependencies, Node >= 18.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const DEFAULT_CONFIG = Object.freeze({
  folders: {
    inbox: '0 - Inbox',
    projects: '1 - Projects',
    areas: '2 - Areas',
    resources: '3 - Resources',
    archives: '4 - Archives',
    journal: 'Journal',
    templates: 'Templates',
  },
  folderTags: {
    inbox: 'inbox',
    projects: 'project',
    areas: 'area',
    resources: 'resource',
    archives: 'archive',
    journal: 'journal',
  },
  ignoreDirs: ['.obsidian', '.trash', '.git', 'node_modules', '.nightshift', 'scripts'],
  rootAllowed: ['HOME.md', 'README.md'],
  generatedNotes: [],
  indexFile: 'VAULT_INDEX.md',
  inboxMax: 10,
  inboxMaxAgeDays: 7,
  maintenanceLock: '.nightshift/maintenance.lock',
});

// ─── CLI ────────────────────────────────────────────────────────────

/** Minimal argv parser: --flag, --flag value, --flag=value, positional args. */
export function parseArgs(argv, booleans = []) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') { positional.push(...argv.slice(i + 1)); break; }
    if (a.startsWith('--') && a.length > 2) {
      const eq = a.indexOf('=');
      const key = eq === -1 ? a.slice(2) : a.slice(2, eq);
      let val = eq === -1 ? undefined : a.slice(eq + 1);
      if (val === undefined) {
        if (booleans.includes(key)) val = true;
        else if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) val = argv[++i];
        else val = true;
      }
      flags[key] = val;
    } else positional.push(a);
  }
  return { positional, flags };
}

export function resolveVault(flags = {}) {
  const v = typeof flags.vault === 'string' ? flags.vault : process.env.NIGHTSHIFT_VAULT;
  if (!v) throw new Error('No vault given: pass --vault <path> or set NIGHTSHIFT_VAULT');
  const abs = path.resolve(v);
  if (!fs.existsSync(abs) || !fs.statSync(abs).isDirectory()) throw new Error(`Vault not found: ${abs}`);
  return abs;
}

export function loadConfig(vault, flags = {}) {
  const candidates = [
    typeof flags.config === 'string' ? path.resolve(flags.config) : null,
    path.join(vault, 'vault.config.json'),
    path.join(vault, '.nightshift', 'vault.config.json'),
  ].filter(Boolean);
  let user = {};
  for (const c of candidates) {
    if (fs.existsSync(c)) { user = JSON.parse(fs.readFileSync(c, 'utf8')); break; }
  }
  return {
    ...DEFAULT_CONFIG,
    ...user,
    folders: { ...DEFAULT_CONFIG.folders, ...(user.folders || {}) },
    folderTags: { ...DEFAULT_CONFIG.folderTags, ...(user.folderTags || {}) },
  };
}

// ─── Paths ──────────────────────────────────────────────────────────

const norm = p => (process.platform === 'win32' ? p.toLowerCase() : p);

export function isInside(parent, child) {
  const p = norm(path.resolve(parent));
  const c = norm(path.resolve(child));
  return c === p || c.startsWith(p.endsWith(path.sep) ? p : p + path.sep);
}

export function sanitizeFilename(name) {
  const s = String(name ?? '')
    .replace(/[\u0000-\u001f]+/g, ' ')
    .replace(/[<>:"|?*\\/]/g, '-')
    .trim();
  if (!s || /^\.+$/.test(s)) throw new Error(`Invalid filename: ${JSON.stringify(name)}`);
  return s;
}

/** PARA role of a vault-relative path ("inbox", "projects", ..., "root" or null). */
export function roleOf(rel, config) {
  const parts = rel.replace(/\\/g, '/').split('/');
  if (parts.length === 1) return 'root';
  for (const [role, dir] of Object.entries(config.folders)) if (parts[0] === dir) return role;
  return null;
}

/**
 * Resolve <vault>/<folder>/<filename>.md and refuse anything that escapes the vault,
 * targets the vault root, the templates folder or an ignored/system directory.
 */
export function safeNotePath(vault, folder, filename, config) {
  if (folder === undefined || folder === null || String(folder).trim() === '') throw new Error('A folder is required (writing at the vault root is not allowed)');
  const f = String(folder).replace(/\\/g, '/');
  if (path.isAbsolute(f) || /^[a-zA-Z]:/.test(f)) throw new Error(`Absolute folder refused: ${folder}`);
  let name = sanitizeFilename(filename);
  if (!name.toLowerCase().endsWith('.md')) name += '.md';
  const dir = path.resolve(vault, f);
  if (!isInside(vault, dir) || norm(dir) === norm(path.resolve(vault))) throw new Error(`Path outside the vault refused: ${folder}/${filename}`);
  const first = path.relative(vault, dir).split(path.sep)[0];
  if (first === config.folders.templates) throw new Error('Writing into the templates folder is not allowed');
  if (config.ignoreDirs.includes(first)) throw new Error(`Writing into ${first} is not allowed`);
  const fp = path.join(dir, name);
  if (!isInside(vault, fp)) throw new Error(`Path outside the vault refused: ${folder}/${filename}`);
  return fp;
}

// ─── IO ─────────────────────────────────────────────────────────────

/** Write to a temp file next to the target, then rename (atomic on the same volume). */
export function atomicWrite(fp, content) {
  fs.mkdirSync(path.dirname(fp), { recursive: true });
  const tmp = `${fp}.${crypto.randomBytes(4).toString('hex')}.tmp`;
  fs.writeFileSync(tmp, content, 'utf8');
  try { fs.renameSync(tmp, fp); } catch (e) { try { fs.unlinkSync(tmp); } catch {} throw e; }
}

/** Recursively list files under the vault. Returns [{abs, rel}] with "/"-separated rel paths. */
export function walk(vault, config, { ext = '.md', includeTemplates = false } = {}) {
  const out = [];
  const skip = new Set(config.ignoreDirs);
  const rec = dir => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (skip.has(e.name)) continue;
      const abs = path.join(dir, e.name);
      const rel = path.relative(vault, abs).replace(/\\/g, '/');
      if (e.isDirectory()) {
        if (!includeTemplates && rel === config.folders.templates) continue;
        rec(abs);
      } else if (!ext || e.name.toLowerCase().endsWith(ext)) {
        if (e.name.endsWith('.tmp')) continue;
        out.push({ abs, rel });
      }
    }
  };
  rec(vault);
  return out.sort((a, b) => a.rel.localeCompare(b.rel));
}

export const today = (d = new Date()) => localDate(d);
export function localDate(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ─── Markdown ───────────────────────────────────────────────────────

const FM_RE = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/;

/**
 * Tiny frontmatter reader: scalar keys, block lists ("key:\n  - a") and flow lists ("key: [a, b]").
 * Returns { present, block, body, fields, flow:Set<key> }.
 */
export function parseFrontmatter(txt) {
  const m = txt.match(FM_RE);
  if (!m) return { present: false, block: '', body: txt, fields: {}, flow: new Set() };
  const fields = {};
  const flow = new Set();
  const lines = m[1].split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const kv = lines[i].match(/^([\w][\w-]*):\s*(.*)$/);
    if (!kv) continue;
    const [, key, rawVal] = kv;
    const val = rawVal.trim();
    if (val.startsWith('[') && val.endsWith(']')) {
      flow.add(key);
      fields[key] = val.slice(1, -1).split(',').map(unquote).filter(Boolean);
    } else if (val === '') {
      const items = [];
      while (i + 1 < lines.length && /^\s+-\s*/.test(lines[i + 1])) items.push(unquote(lines[++i].replace(/^\s+-\s*/, '')));
      fields[key] = items.length ? items : '';
    } else fields[key] = unquote(val);
  }
  return { present: true, block: m[1], body: txt.slice(m[0].length), fields, flow };
}

export const unquote = s => String(s).trim().replace(/^["']|["']$/g, '').replace(/\\"/g, '"').trim();

export const firstH1 = body => { const h = body.match(/^# (.+)$/m); return h ? h[1].trim() : null; };

/** Replace fenced code blocks and inline code spans with blanks (offsets preserved). */
export function maskCode(txt) {
  return txt
    .replace(/(^|\n)(```|~~~)[\s\S]*?(\n\2[^\n]*|$)/g, m => m.replace(/[^\n]/g, ' '))
    .replace(/`[^`\n]*`/g, m => ' '.repeat(m.length));
}

/** Normalise a wikilink target: drop alias/anchor, folder prefix and .md suffix. */
export function linkTarget(inner) {
  let t = inner.split('|')[0].split('#')[0].replace(/\s*\n\s*/g, ' ').trim();
  if (t.includes('/')) t = t.split('/').pop();
  if (t.toLowerCase().endsWith('.md')) t = t.slice(0, -3);
  return t;
}

export function extractLinks(txt) {
  const masked = maskCode(txt);
  const links = [];
  for (const m of masked.matchAll(/(!?)\[\[([^\]]*?)\]\]/g)) {
    links.push({ raw: m[0], inner: m[2], target: linkTarget(m[2]), embed: m[1] === '!', index: m.index });
  }
  return links;
}

export const fold = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/** Build a link resolver over the whole vault (notes, aliases, attachments). */
export function buildResolver(vault, config) {
  const notes = walk(vault, config, { includeTemplates: false });
  const names = new Map();       // basename -> rel
  const aliases = new Map();     // alias -> basename (only when no note has that name)
  const allAliases = [];         // [alias, basename] including collisions
  for (const n of notes) names.set(path.basename(n.rel, '.md'), n.rel);
  for (const n of notes) {
    const fm = parseFrontmatter(fs.readFileSync(n.abs, 'utf8'));
    const al = fm.fields.aliases;
    for (const a of Array.isArray(al) ? al : al ? [al] : []) {
      allAliases.push([a, path.basename(n.rel, '.md')]);
      if (!names.has(a)) aliases.set(a, path.basename(n.rel, '.md'));
    }
  }
  const attachments = new Set(walk(vault, config, { ext: null, includeTemplates: true })
    .filter(f => !f.rel.toLowerCase().endsWith('.md')).map(f => path.basename(f.rel)));
  const folded = new Map();
  for (const n of names.keys()) {
    const k = fold(n);
    folded.set(k, folded.has(k) ? null : n); // null = ambiguous
  }
  return {
    notes, names, aliases, allAliases,
    resolve(t) {
      if (names.has(t)) return t;
      if (aliases.has(t)) return aliases.get(t);
      if (attachments.has(t)) return t;
      return null;
    },
    suggest(t) { return folded.get(fold(t)) || null; },
  };
}

export function isGenerated(rel, config) {
  const base = path.basename(rel);
  return (config.generatedNotes || []).some(p => {
    try { return new RegExp(p).test(base) || new RegExp(p).test(rel); } catch { return p === base || p === rel; }
  });
}

/** True when the calling module is the process entry point. */
export async function isMain(importMetaUrl) {
  if (!process.argv[1]) return false;
  const { fileURLToPath } = await import('node:url');
  try { return norm(fs.realpathSync(process.argv[1])) === norm(fs.realpathSync(fileURLToPath(importMetaUrl))); } catch { return false; }
}
