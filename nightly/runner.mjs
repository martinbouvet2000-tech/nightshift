#!/usr/bin/env node
// runner.mjs — the night shift. Runs the consolidation prompt through `claude -p` against a vault,
// unattended, and guarantees (whatever the agent does):
//   - a deterministic work window: since last success, at least 36 h, at most 7 days
//   - the right journal date: a run before 06:00 consolidates the PREVIOUS day
//   - a single instance (lock file) and respect of the vault maintenance lock
//   - a hard timeout per attempt, one retry after a delay on session-limit / API errors
//   - verification of the final `NIGHTSHIFT_OK <journal> notes=N links=N proposals=N` line
//   - a failure trace in the journal note when the agent left no report (absence = signal)
//   - persistent state (last_success, counters) in state.json
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseArgs, loadConfig, walk, isGenerated, localDate, isMain } from '../vault/lib.mjs';
import { journal as writerJournal } from '../vault/vault-writer.mjs';
import { audit } from '../vault/audit.mjs';
import { backup } from '../vault/backup.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const DEFAULTS = Object.freeze({
  model: 'claude-sonnet-5',
  claude: 'claude',
  timeoutMin: 18,
  retryWaitMin: 20,
  minWindowHours: 36,
  maxWindowDays: 7,
  dayStartHour: 6,
  maxCandidates: 40,
  maxLogs: 30,
  permissionMode: 'acceptEdits',
  // Empty on purpose: Claude Code already limits Read/Glob/Grep, and Edit/Write under acceptEdits,
  // to the working directory (the vault). A bare 'Read' or 'Bash(git diff:*)' here would let a
  // prompt-injected transcript read or write files outside the vault. See README > Threat model.
  allowedTools: '',
});

const HELP = `runner — run the nightshift consolidation agent on a vault

Usage: node runner.mjs [--vault <path>] [options]

  --vault <path>        vault to consolidate (or NIGHTSHIFT_VAULT)
  --state-dir <path>    state, lock and logs (default ~/.nightshift/nightly, or NIGHTSHIFT_STATE_DIR)
  --prompt <file>       prompt template (default nightly-prompt.md next to this script)
  --model <id>          model id (default ${DEFAULTS.model}, or NIGHTSHIFT_MODEL)
  --claude <bin>        Claude Code executable (default "claude", or NIGHTSHIFT_CLAUDE)
  --timeout-min <n>     hard timeout per attempt (default ${DEFAULTS.timeoutMin})
  --retry-wait-min <n>  delay before the single retry (default ${DEFAULTS.retryWaitMin})
  --allowed-tools <s>   value passed to --allowedTools
  --permission-mode <m> value passed to --permission-mode (default ${DEFAULTS.permissionMode})
  --journal <date>      force the journal date (YYYY-MM-DD)
  --backup              run vault/backup.mjs after the agent (git commit + push if the vault is a repo)
  --dry-run             print the exact command and exit, without calling claude or writing anything
  --print-prompt        with --dry-run, also print the rendered prompt

Exit codes: 0 success or clean skip, 1 failure, 3 another run holds the lock.`;

// ─── Pure helpers (unit-tested) ─────────────────────────────────────

const pad = n => String(n).padStart(2, '0');

/** Journal date: the previous day when the run starts before dayStartHour (local time). */
export function journalDate(now, dayStartHour = DEFAULTS.dayStartHour) {
  const d = new Date(now);
  if (d.getHours() < dayStartHour) d.setDate(d.getDate() - 1);
  return localDate(d);
}

/** Window start: since the last success, clamped to [minWindowHours, maxWindowDays] back from now. */
export function computeSince(now, lastSuccess, { minWindowHours = DEFAULTS.minWindowHours, maxWindowDays = DEFAULTS.maxWindowDays } = {}) {
  const t = new Date(now).getTime();
  const latest = t - minWindowHours * 3600e3;
  const earliest = t - maxWindowDays * 86400e3;
  const ls = lastSuccess ? Date.parse(lastSuccess) : NaN;
  if (!Number.isFinite(ls) || ls >= latest) return new Date(latest);
  return new Date(Math.max(ls, earliest));
}

/** Local ISO-8601 timestamp with offset, e.g. 2026-01-10T00:30:00+01:00. */
export function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  return `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
}

export const runIdFor = d => `${localDate(d)}_${pad(d.getHours())}${pad(d.getMinutes())}`;

const OK_RE = /^[ \t>*`]*NIGHTSHIFT_OK[ \t]+(\d{4}-\d{2}-\d{2})[ \t]+notes=(\d+)[ \t]+links=(\d+)[ \t]+proposals=(\d+)[ \t`*]*$/gm;

/** Last well-formed OK line in the output, or null. With `journal`, the date must match. */
export function parseOkLine(text, journal) {
  let last = null;
  for (const m of String(text || '').matchAll(OK_RE)) last = m;
  if (!last) return null;
  const r = { journal: last[1], notes: +last[2], links: +last[3], proposals: +last[4] };
  if (journal && r.journal !== journal) return null;
  return r;
}

/** Map a finished attempt to a status: ok | limit | api | timeout | noack | error. */
export function classify({ code, stdout = '', stderr = '', timedOut = false }, journal) {
  if (timedOut) return 'timeout';
  const all = `${stdout}\n${stderr}`;
  if (parseOkLine(stdout, journal)) return 'ok';
  if (/session limit|usage limit|rate limit|hit your limit|limit reached/i.test(all)) return 'limit';
  if (/API Error|overloaded|ECONNREFUSED|ECONNRESET|ENOTFOUND|ETIMEDOUT|Connection refused|\b5\d\d\b.*error/i.test(all)) return 'api';
  if (code === 0) return 'noack';
  return 'error';
}

// ─── Lock ───────────────────────────────────────────────────────────

function pidAlive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

/** Exclusive lock file. A lock older than staleMs, or whose owner process is gone, is taken over. */
export function acquireLock(file, { staleMs, now = Date.now(), pid = process.pid } = {}) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const body = JSON.stringify({ pid, started: new Date(now).toISOString() });
  try { fs.writeFileSync(file, body, { flag: 'wx' }); return { ok: true }; } catch (e) { if (e.code !== 'EEXIST') throw e; }
  let info = {};
  try { info = JSON.parse(fs.readFileSync(file, 'utf8')); } catch {}
  const started = Date.parse(info.started);
  const stale = !Number.isFinite(started) || (staleMs && now - started > staleMs) || !pidAlive(info.pid);
  if (!stale) return { ok: false, reason: `locked by pid ${info.pid} since ${info.started}` };
  // Take over atomically: remove the stale lock, then race for a fresh exclusive create.
  try { fs.unlinkSync(file); } catch {}
  try { fs.writeFileSync(file, body, { flag: 'wx' }); } catch (e) {
    if (e.code === 'EEXIST') return { ok: false, reason: 'lock taken over by another runner' };
    throw e;
  }
  return { ok: true, tookOver: true };
}

export function releaseLock(file, pid = process.pid) {
  try {
    const info = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (info.pid === pid) fs.unlinkSync(file);
  } catch {}
}

// ─── Journal failure trace ──────────────────────────────────────────

export const reportHeading = journal => `## Nightshift — ${journal}`;

export function journalPath(vault, config, journal) {
  return path.join(vault, config.folders.journal, `${journal}.md`);
}

export function hasReport(vault, config, journal) {
  const fp = journalPath(vault, config, journal);
  return fs.existsSync(fp) && fs.readFileSync(fp, 'utf8').includes(reportHeading(journal));
}

/** Append a deterministic failure block to the journal note (created with contract frontmatter if missing). */
export function writeFailureTrace(vault, config, journal, { runId, model, reason, logFile, rerun }) {
  const fp = journalPath(vault, config, journal);
  if (!fs.existsSync(fp)) writerJournal(vault, config, '', journal);
  const existing = fs.readFileSync(fp, 'utf8');
  const eol = existing.includes('\r\n') ? '\r\n' : '\n';
  const lines = [
    '', reportHeading(journal), `_run ${runId} · model ${model}_`, '',
    `- FAILED: ${reason}.${logFile ? ` Log: \`${logFile}\`.` : ''}${rerun ? ` Re-run: \`${rerun}\`.` : ''}`, '',
  ];
  fs.appendFileSync(fp, (existing.endsWith('\n') ? '' : eol) + lines.join(eol), 'utf8');
  return fp;
}

// ─── Context gathering ──────────────────────────────────────────────

/** Notes changed since the window start: file mtime and, when the vault is a git repo, git log. */
export function changedNotes(vault, config, since, max = DEFAULTS.maxCandidates) {
  const byRel = new Map();
  for (const f of walk(vault, config)) {
    if (f.rel === config.indexFile || f.rel.startsWith(config.folders.journal + '/') || isGenerated(f.rel, config)) continue;
    const m = fs.statSync(f.abs).mtimeMs;
    if (m >= since.getTime()) byRel.set(f.rel, m);
  }
  if (fs.existsSync(path.join(vault, '.git'))) {
    const r = spawnSync('git', ['log', `--since=${since.toISOString()}`, '--name-only', '--pretty=format:', '--', '*.md'], { cwd: vault, encoding: 'utf8', windowsHide: true });
    for (const rel of (r.stdout || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean)) {
      const abs = path.join(vault, rel);
      if (!byRel.has(rel) && fs.existsSync(abs) && !rel.startsWith(config.folders.journal + '/') && !rel.startsWith(config.folders.templates + '/') && !isGenerated(rel, config)) byRel.set(rel, fs.statSync(abs).mtimeMs);
    }
  }
  const all = [...byRel.entries()].sort((a, b) => b[1] - a[1]).map(([rel]) => rel);
  return { list: all.slice(0, max), total: all.length };
}

export function renderPrompt(template, vars) {
  return template.replace(/\{\{([A-Z_]+)\}\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

function auditSummary(vault, config) {
  try {
    const r = audit(vault, config);
    const broken = r.issues.filter(i => i.rule === 'broken-link').slice(0, 20).map(i => `${i.file}: ${i.detail}`);
    return JSON.stringify({ notes: r.summary.notes, linksPerNote: r.summary.linksPerNote, errors: r.summary.errors, warnings: r.summary.warnings, byRule: r.summary.byRule, brokenLinks: broken }, null, 2);
  } catch (e) {
    return `audit unavailable: ${e.message}`;
  }
}

// ─── Claude invocation ──────────────────────────────────────────────

export function buildCommand(o) {
  return {
    bin: o.claude,
    args: ['-p', '--model', o.model, '--output-format', 'text', '--permission-mode', o.permissionMode,
      ...(o.allowedTools ? ['--allowedTools', o.allowedTools] : []), '--add-dir', o.vault],
    cwd: o.vault,
  };
}

const quote = a => {
  const s = String(a);
  if (/^[\w@%+=:,./\\-]+$/.test(s)) return s;
  return process.platform === 'win32' ? `"${s.replace(/"/g, '\\"')}"` : `'${s.replace(/'/g, `'\\''`)}'`;
};
export const formatCommand = c => [c.bin, ...c.args].map(quote).join(' ');

function resolveBin(bin) {
  if (process.platform !== 'win32' || path.extname(bin)) return bin;
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    for (const ext of ['.exe', '.cmd', '.bat']) {
      const p = path.join(dir, bin + ext);
      if (fs.existsSync(p)) return p;
    }
  }
  return bin;
}

/** Default invoker: spawn claude, feed the prompt on stdin, enforce the timeout (kills the whole tree). */
export function spawnClaude({ bin, args, cwd }, prompt, timeoutMs) {
  return new Promise(resolve => {
    const exe = resolveBin(bin);
    const viaShell = process.platform === 'win32' && /\.(cmd|bat)$/i.test(exe);
    const child = viaShell
      ? spawn(`"${exe}" ${args.map(a => `"${a.replace(/"/g, '""')}"`).join(' ')}`, { cwd, shell: true, windowsHide: true })
      : spawn(exe, args, { cwd, windowsHide: true, detached: process.platform !== 'win32' });
    let stdout = '', stderr = '', timedOut = false, done = false;
    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });
    const timer = setTimeout(() => {
      timedOut = true;
      if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
      else { try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); } }
    }, timeoutMs);
    const finish = code => { if (done) return; done = true; clearTimeout(timer); resolve({ code, stdout, stderr, timedOut }); };
    child.on('error', e => { stderr += String(e.message); finish(127); });
    child.on('close', code => finish(code));
    child.stdin.on('error', () => {});
    child.stdin.end(prompt);
  });
}

// ─── State ──────────────────────────────────────────────────────────

export function readState(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; }
}
function writeState(file, state) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(state, null, 2) + '\n');
  fs.renameSync(tmp, file);
}

// ─── Orchestration ──────────────────────────────────────────────────

export function resolveOptions(flags, env = process.env) {
  const vault = path.resolve(flags.vault || env.NIGHTSHIFT_VAULT || '');
  if (!(flags.vault || env.NIGHTSHIFT_VAULT)) throw new Error('No vault given: pass --vault <path> or set NIGHTSHIFT_VAULT');
  if (!fs.existsSync(vault)) throw new Error(`Vault not found: ${vault}`);
  const num = (v, d) => (v === undefined || v === true ? d : Number(v));
  return {
    vault,
    stateDir: path.resolve(flags['state-dir'] || env.NIGHTSHIFT_STATE_DIR || path.join(os.homedir(), '.nightshift', 'nightly')),
    promptFile: path.resolve(flags.prompt || path.join(HERE, 'nightly-prompt.md')),
    model: flags.model || env.NIGHTSHIFT_MODEL || DEFAULTS.model,
    claude: flags.claude || env.NIGHTSHIFT_CLAUDE || DEFAULTS.claude,
    timeoutMin: num(flags['timeout-min'], DEFAULTS.timeoutMin),
    retryWaitMin: num(flags['retry-wait-min'], DEFAULTS.retryWaitMin),
    allowedTools: flags['allowed-tools'] || DEFAULTS.allowedTools,
    permissionMode: flags['permission-mode'] || DEFAULTS.permissionMode,
    journal: typeof flags.journal === 'string' ? flags.journal : null,
    backup: !!flags.backup,
    dryRun: !!flags['dry-run'],
    printPrompt: !!flags['print-prompt'],
    config: typeof flags.config === 'string' ? flags.config : undefined,
  };
}

/**
 * Run one night shift. `deps` lets tests inject { invoke, sleep, now, log, backupFn }.
 * Returns { status, exitCode, ... }.
 */
export async function runNightly(o, deps = {}) {
  const now = deps.now ? new Date(deps.now) : new Date();
  const out = deps.log || (m => console.log(m));
  const invoke = deps.invoke || spawnClaude;
  const sleep = deps.sleep || (ms => new Promise(r => setTimeout(r, ms)));
  const config = loadConfig(o.vault, { config: o.config });
  const stateFile = path.join(o.stateDir, 'state.json');
  const lockFile = path.join(o.stateDir, 'runner.lock');
  const logDir = path.join(o.stateDir, 'logs');
  const runId = runIdFor(now);
  const state = readState(stateFile);
  const journal = o.journal || journalDate(now);
  const since = computeSince(now, state.last_success);
  const sinceIso = isoLocal(since);
  const cmd = buildCommand(o);

  const candidates = changedNotes(o.vault, config, since);
  const vars = {
    VAULT: o.vault, SINCE: sinceIso, JOURNAL: journal, RUN_ID: runId, MODEL: o.model,
    JOURNAL_FILE: path.posix.join(config.folders.journal, `${journal}.md`),
    FOLDERS: JSON.stringify(config.folders), GENERATED: JSON.stringify(config.generatedNotes || []),
    INDEX_FILE: config.indexFile, INBOX_MAX: config.inboxMax, MAINTENANCE_LOCK: config.maintenanceLock,
    CANDIDATES: candidates.list.length ? candidates.list.map(r => `- ${r}`).join('\n') + (candidates.total > candidates.list.length ? `\n- (${candidates.total - candidates.list.length} older changes not listed: budget ${DEFAULTS.maxCandidates})` : '') : '- (none)',
    AUDIT: auditSummary(o.vault, config),
  };
  const prompt = renderPrompt(fs.readFileSync(o.promptFile, 'utf8'), vars);

  if (o.dryRun) {
    out(`journal=${journal} since=${sinceIso} run_id=${runId} model=${o.model} candidates=${candidates.total}`);
    out(`cwd: ${cmd.cwd}`);
    out(`command: ${formatCommand(cmd)}`);
    out(`stdin: rendered ${path.basename(o.promptFile)} (${prompt.length} chars)`);
    out(`timeout: ${o.timeoutMin} min, retry after ${o.retryWaitMin} min on limit/API errors`);
    if (o.printPrompt) out('\n' + prompt);
    return { status: 'dry-run', exitCode: 0, command: cmd, prompt, journal, since: sinceIso, runId };
  }

  fs.mkdirSync(logDir, { recursive: true });
  const logFile = path.join(logDir, `run_${runId}.log`);
  const log = m => { const line = `${new Date().toISOString()} ${m}`; fs.appendFileSync(logFile, line + '\n'); out(m); };

  if (fs.existsSync(path.join(o.vault, config.maintenanceLock))) {
    log('maintenance lock present: night shift skipped (nothing written)');
    return { status: 'skipped-maintenance', exitCode: 0 };
  }
  const staleMs = (2 * o.timeoutMin + o.retryWaitMin + 10) * 60e3;
  const lock = acquireLock(lockFile, { staleMs, now: now.getTime() });
  if (!lock.ok) { log(`another run is active (${lock.reason}): exiting`); return { status: 'locked', exitCode: 3 }; }

  let status = 'error', result = null, ack = null;
  try {
    log(`run ${runId}: journal=${journal} since=${sinceIso} model=${o.model} candidates=${candidates.total}${lock.tookOver ? ' (stale lock taken over)' : ''}`);
    for (let attempt = 1; attempt <= 2; attempt++) {
      log(`attempt ${attempt}: ${formatCommand(cmd)}`);
      result = await invoke(cmd, prompt, o.timeoutMin * 60e3, { attempt });
      fs.writeFileSync(path.join(logDir, `out_${runId}_${attempt}.txt`), `${result.stdout || ''}\n--- stderr ---\n${result.stderr || ''}`);
      status = classify(result, journal);
      log(`attempt ${attempt}: exit=${result.code} status=${status} output=${(result.stdout || '').length} chars`);
      if (attempt === 1 && (status === 'limit' || status === 'api')) {
        log(`retrying in ${o.retryWaitMin} min`);
        await sleep(o.retryWaitMin * 60e3);
        continue;
      }
      break;
    }
    ack = parseOkLine(result?.stdout, journal);
    const reported = hasReport(o.vault, config, journal);
    const success = status === 'ok' || (status === 'noack' && reported);
    const next = {
      ...state,
      runs_total: (state.runs_total || 0) + 1,
      last_run: now.toISOString(),
      last_status: status,
      last_run_id: runId,
    };
    if (success) {
      Object.assign(next, {
        last_success: now.toISOString(), journal, run_id: runId, model: o.model,
        notes: ack?.notes ?? null, links: ack?.links ?? null, proposals: ack?.proposals ?? null,
        consecutive_failures: 0,
      });
    } else {
      next.failures_total = (state.failures_total || 0) + 1;
      next.consecutive_failures = (state.consecutive_failures || 0) + 1;
      if (!reported) {
        const reason = {
          limit: 'Claude session/usage limit reached (2 attempts)',
          api: 'API or network error (2 attempts)',
          timeout: `timeout after ${o.timeoutMin} min`,
          noack: 'agent exited without the NIGHTSHIFT_OK line and without a report',
        }[status] || `agent failed (exit ${result?.code})`;
        const rerun = `node ${quote(path.join(HERE, 'runner.mjs'))} --vault ${quote(o.vault)}`;
        writeFailureTrace(o.vault, config, journal, { runId, model: o.model, reason, logFile, rerun });
        log('failure trace appended to the journal note');
      }
    }
    writeState(stateFile, next);
    status = success ? 'ok' : status;
  } finally {
    releaseLock(lockFile);
  }

  if (o.backup) {
    try { (deps.backupFn || backup)(o.vault, config, { reason: 'nightly', log }); } catch (e) { log(`backup error: ${e.message}`); }
  }
  rotateLogs(logDir, DEFAULTS.maxLogs);
  log(`end: ${status}`);
  return { status, exitCode: status === 'ok' ? 0 : 1, ack, journal, since: sinceIso, runId };
}

function rotateLogs(dir, keep) {
  try {
    for (const prefix of ['run_', 'out_']) {
      fs.readdirSync(dir).filter(f => f.startsWith(prefix))
        .map(f => ({ f, t: fs.statSync(path.join(dir, f)).mtimeMs })).sort((a, b) => b.t - a.t)
        .slice(keep * (prefix === 'out_' ? 2 : 1)).forEach(({ f }) => fs.unlinkSync(path.join(dir, f)));
    }
  } catch {}
}

async function main(argv) {
  const { flags } = parseArgs(argv, ['dry-run', 'print-prompt', 'backup', 'help']);
  if (flags.help) { console.log(HELP); return 0; }
  const r = await runNightly(resolveOptions(flags));
  return r.exitCode;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = await main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 1; }
}
