import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { loadConfig, parseFrontmatter } from '../../vault/lib.mjs';
import {
  journalDate, computeSince, parseOkLine, classify, acquireLock, releaseLock,
  writeFailureTrace, runNightly, resolveOptions, readState,
  missedNights, writeGapNote, gapMarker, keepAwakeCommand,
} from '../runner.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, '..', '..', 'vault', 'test', 'fixtures', 'sample-vault');
const RUNNER = path.join(here, '..', 'runner.mjs');
const tmp = [];
after(() => { for (const d of tmp) fs.rmSync(d, { recursive: true, force: true }); });

function mkTmp(prefix) { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); tmp.push(d); return d; }
function tmpVault() { const d = mkTmp('nightshift-nv-'); fs.cpSync(FIXTURE, d, { recursive: true }); return d; }
const H = 3600e3;

test('journal date: previous day before 06:00, same day after', () => {
  assert.equal(journalDate(new Date(2026, 0, 11, 0, 30)), '2026-01-10');
  assert.equal(journalDate(new Date(2026, 0, 11, 5, 59)), '2026-01-10');
  assert.equal(journalDate(new Date(2026, 0, 11, 6, 0)), '2026-01-11');
  assert.equal(journalDate(new Date(2026, 0, 11, 23, 0)), '2026-01-11');
  assert.equal(journalDate(new Date(2026, 2, 1, 1, 0)), '2026-02-28', 'month boundary');
  assert.equal(journalDate(new Date(2026, 0, 1, 2, 0)), '2025-12-31', 'year boundary');
});

test('since window: last success, at least 36 h, at most 7 days', () => {
  const now = new Date(2026, 0, 20, 5, 30);
  const t = now.getTime();
  assert.equal(computeSince(now, null).getTime(), t - 36 * H, 'no state -> 36 h');
  assert.equal(computeSince(now, 'garbage').getTime(), t - 36 * H, 'unreadable -> 36 h');
  assert.equal(computeSince(now, new Date(t - 24 * H).toISOString()).getTime(), t - 36 * H, 'recent success -> still 36 h');
  assert.equal(computeSince(now, new Date(t - 72 * H).toISOString()).getTime(), t - 72 * H, 'missed nights -> since last success');
  assert.equal(computeSince(now, new Date(t - 30 * 24 * H).toISOString()).getTime(), t - 7 * 24 * H, 'capped at 7 days');
  assert.equal(computeSince(now, new Date(t + H).toISOString()).getTime(), t - 36 * H, 'future timestamp -> 36 h');
});

test('OK line parsing', () => {
  const out = 'report written\nNIGHTSHIFT_OK 2026-01-10 notes=4 links=7 proposals=2\n';
  assert.deepEqual(parseOkLine(out), { journal: '2026-01-10', notes: 4, links: 7, proposals: 2 });
  assert.deepEqual(parseOkLine(out, '2026-01-10')?.links, 7);
  assert.equal(parseOkLine(out, '2026-01-11'), null, 'wrong journal date is rejected');
  assert.equal(parseOkLine('NIGHTSHIFT_OK 2026-01-10 notes=4 links=x proposals=2'), null);
  assert.equal(parseOkLine('the agent says NIGHTSHIFT_OK 2026-01-10 notes=1 links=1 proposals=1 inline'), null, 'must be its own line');
  assert.equal(parseOkLine('`NIGHTSHIFT_OK 2026-01-10 notes=1 links=2 proposals=3`')?.proposals, 3, 'tolerates code formatting');
  assert.equal(parseOkLine('NIGHTSHIFT_OK 2026-01-10 notes=1 links=1 proposals=1\nNIGHTSHIFT_OK 2026-01-10 notes=9 links=9 proposals=9').notes, 9, 'last line wins');
  assert.equal(classify({ code: 0, stdout: out }, '2026-01-10'), 'ok');
  assert.equal(classify({ code: 1, stdout: '', stderr: 'Claude usage limit reached' }), 'limit');
  assert.equal(classify({ code: 1, stdout: 'API Error: 529 overloaded' }), 'api');
  assert.equal(classify({ code: 0, stdout: 'done' }), 'noack');
  assert.equal(classify({ code: 2, stdout: '' }), 'error');
  assert.equal(classify({ code: null, timedOut: true }), 'timeout');
});

test('lock: exclusive, stale or dead-owner locks are taken over, release removes it', () => {
  const dir = mkTmp('nightshift-lock-');
  const file = path.join(dir, 'runner.lock');
  const now = Date.now();
  assert.equal(acquireLock(file, { staleMs: 60e3, now }).ok, true);
  const second = acquireLock(file, { staleMs: 60e3, now: now + 1000 });
  assert.equal(second.ok, false, 'held by a live process');
  assert.match(second.reason, /locked by pid/);
  const stale = acquireLock(file, { staleMs: 60e3, now: now + 120e3, pid: 999999 });
  assert.equal(stale.ok, true);
  assert.equal(stale.tookOver, true);
  releaseLock(file, process.pid);
  assert.ok(fs.existsSync(file), 'only the owner may release');
  releaseLock(file, 999999);
  assert.ok(!fs.existsSync(file));
  fs.writeFileSync(file, JSON.stringify({ pid: 999999, started: new Date(now).toISOString() }));
  assert.equal(acquireLock(file, { staleMs: 3600e3, now }).tookOver, true, 'dead owner');
});

test('failure trace: creates a contract journal note and appends a block', () => {
  const v = tmpVault(); const cfg = loadConfig(v);
  const fp = writeFailureTrace(v, cfg, '2026-02-02', { runId: 'r1', model: 'm', reason: 'timeout after 18 min', logFile: '/logs/run.log' });
  const txt = fs.readFileSync(fp, 'utf8');
  const fm = parseFrontmatter(txt);
  assert.deepEqual(fm.fields.tags, ['journal']);
  assert.equal(fm.fields.created, '2026-02-02');
  assert.match(txt, /^# 2026-02-02$/m);
  assert.match(txt, /## Nightshift — 2026-02-02\n_run r1 · model m_\n\n- FAILED: timeout after 18 min\. Log: `\/logs\/run\.log`\./);
  // Existing note: owner content preserved, block appended at the end.
  const existing = path.join(v, 'Journal', '2026-01-10.md');
  const before = fs.readFileSync(existing, 'utf8');
  writeFailureTrace(v, cfg, '2026-01-10', { runId: 'r2', model: 'm', reason: 'x' });
  const afterTxt = fs.readFileSync(existing, 'utf8');
  assert.ok(afterTxt.startsWith(before));
  assert.match(afterTxt, /- FAILED: x\.\n$/);
});

function opts(v, extra = {}) {
  return { ...resolveOptions({ vault: v, 'state-dir': mkTmp('nightshift-state-') }), keepAwake: false, ...extra };
}

test('runNightly success: OK line verified, state persisted, no failure trace', async () => {
  const v = tmpVault(); const o = opts(v);
  const calls = [];
  const now = new Date(2026, 0, 11, 0, 30);
  const r = await runNightly(o, {
    now, log: () => {},
    invoke: async (cmd, prompt) => { calls.push({ cmd, prompt }); return { code: 0, stdout: 'ok\nNIGHTSHIFT_OK 2026-01-10 notes=3 links=2 proposals=1\n', stderr: '' }; },
  });
  assert.equal(r.status, 'ok');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].cmd.args[0], '-p');
  assert.ok(calls[0].cmd.args.includes('claude-sonnet-5'));
  assert.match(calls[0].prompt, /Journal date: `2026-01-10`/);
  assert.doesNotMatch(calls[0].prompt, /\{\{[A-Z_]+\}\}/, 'all placeholders rendered');
  const st = readState(path.join(o.stateDir, 'state.json'));
  assert.equal(st.last_success, now.toISOString());
  assert.equal(st.journal, '2026-01-10');
  assert.deepEqual([st.notes, st.links, st.proposals], [3, 2, 1]);
  assert.equal(st.runs_total, 1);
  assert.equal(st.consecutive_failures, 0);
  assert.doesNotMatch(fs.readFileSync(path.join(v, 'Journal', '2026-01-10.md'), 'utf8'), /FAILED/);
  assert.ok(!fs.existsSync(path.join(o.stateDir, 'runner.lock')), 'lock released');
});

test('runNightly: one retry on limit, then failure trace + counters', async () => {
  const v = tmpVault(); const o = opts(v);
  let calls = 0; const sleeps = [];
  const r = await runNightly(o, {
    now: new Date(2026, 0, 11, 0, 30), log: () => {},
    sleep: async ms => { sleeps.push(ms); },
    invoke: async () => { calls++; return { code: 1, stdout: '', stderr: 'You have hit your limit' }; },
  });
  assert.equal(r.status, 'limit');
  assert.equal(r.exitCode, 1);
  assert.equal(calls, 2, 'exactly one retry');
  assert.deepEqual(sleeps, [20 * 60e3]);
  const st = readState(path.join(o.stateDir, 'state.json'));
  assert.equal(st.last_success, undefined);
  assert.equal(st.failures_total, 1);
  assert.match(fs.readFileSync(path.join(v, 'Journal', '2026-01-10.md'), 'utf8'), /- FAILED: Claude session\/usage limit reached \(2 attempts\)/);
});

test('runNightly: no retry on timeout; agent report without OK line counts as success; lock and maintenance honoured', async () => {
  const v = tmpVault();
  let o = opts(v); let calls = 0;
  let r = await runNightly(o, { now: new Date(2026, 0, 11, 7), log: () => {}, invoke: async () => { calls++; return { code: null, stdout: '', stderr: '', timedOut: true }; } });
  assert.equal(r.status, 'timeout'); assert.equal(calls, 1);
  assert.match(fs.readFileSync(path.join(v, 'Journal', '2026-01-11.md'), 'utf8'), /FAILED: timeout after 18 min/);

  o = opts(v);
  r = await runNightly(o, {
    now: new Date(2026, 0, 12, 7), log: () => {},
    invoke: async () => { fs.writeFileSync(path.join(v, 'Journal', '2026-01-12.md'), '---\ntags:\n  - journal\n---\n\n# 2026-01-12\n\n## Nightshift — 2026-01-12\nRAS\n'); return { code: 0, stdout: 'done', stderr: '' }; },
  });
  assert.equal(r.status, 'ok');

  o = opts(v);
  fs.writeFileSync(path.join(o.stateDir, 'runner.lock'), JSON.stringify({ pid: process.pid, started: new Date().toISOString() }));
  r = await runNightly(o, { log: () => {}, invoke: async () => assert.fail('must not run while locked') });
  assert.equal(r.exitCode, 3);

  o = opts(v);
  fs.mkdirSync(path.join(v, '.nightshift'), { recursive: true });
  fs.writeFileSync(path.join(v, '.nightshift', 'maintenance.lock'), '');
  r = await runNightly(o, { log: () => {}, invoke: async () => assert.fail('must not run under maintenance lock') });
  assert.equal(r.status, 'skipped-maintenance'); assert.equal(r.exitCode, 0);
});

test('CLI --dry-run prints the exact command and writes nothing', () => {
  const v = tmpVault(); const state = mkTmp('nightshift-state-');
  const r = spawnSync(process.execPath, [RUNNER, '--dry-run', '--vault', v, '--state-dir', state], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /command: claude -p --model claude-sonnet-5 /);
  assert.doesNotMatch(r.stdout, /--allowedTools "?Read/);
  assert.deepEqual(fs.readdirSync(state), [], 'no state, lock or log written');
});

test('default invoker feeds the prompt on stdin and kills the process tree on timeout', async () => {
  const { spawnClaude } = await import('../runner.mjs');
  const echo = await spawnClaude({ bin: process.execPath, args: ['-e', 'process.stdin.pipe(process.stdout)'], cwd: os.tmpdir() }, 'hello prompt', 10e3);
  assert.equal(echo.code, 0);
  assert.equal(echo.stdout, 'hello prompt');
  const t0 = Date.now();
  const slow = await spawnClaude({ bin: process.execPath, args: ['-e', 'setTimeout(() => {}, 30000)'], cwd: os.tmpdir() }, '', 300);
  assert.equal(slow.timedOut, true);
  assert.ok(Date.now() - t0 < 10e3);
});

test('missed nights: null when recent or unknown, counted otherwise', () => {
  const now = new Date(2026, 0, 20, 0, 30);
  const t = now.getTime();
  assert.equal(missedNights(now, null), null, 'first run is not a gap');
  assert.equal(missedNights(now, new Date(t - 24 * H).toISOString()), null, 'last night ran');
  assert.equal(missedNights(now, new Date(t - 29 * H).toISOString()), null, 'late run, still not a gap');
  assert.equal(missedNights(now, new Date(t - 49 * H).toISOString()).nights, 2);
  assert.equal(missedNights(now, new Date(t - 31 * H).toISOString()).nights, 1);
});

test('gap note: written once per journal date, contract journal created if missing', () => {
  const v = tmpVault(); const config = loadConfig(v);
  const since = new Date(2026, 0, 12, 0, 31);
  const fp = writeGapNote(v, config, '2026-01-15', { since, nights: 3 });
  const txt = fs.readFileSync(fp, 'utf8');
  assert.equal(parseFrontmatter(txt).present, true);
  assert.match(txt, /3 nights missed/);
  assert.equal(writeGapNote(v, config, '2026-01-15', { since, nights: 3 }), null, 'idempotent');
  assert.equal(fs.readFileSync(fp, 'utf8').split(gapMarker('2026-01-15')).length, 2);
});

test('keep-awake: one helper per platform, each bound to the runner pid', () => {
  const w = keepAwakeCommand('win32', 4242);
  assert.equal(w.bin, 'powershell');
  assert.match(w.args.at(-1), /SetThreadExecutionState\(2147483649\)/);
  assert.match(w.args.at(-1), /Get-Process -Id 4242/);
  assert.deepEqual(keepAwakeCommand('darwin', 4242), { bin: 'caffeinate', args: ['-i', '-w', '4242'] });
  assert.ok(keepAwakeCommand('linux', 4242).args.includes('--pid=4242'));
  assert.equal(keepAwakeCommand('aix', 4242), null);
});

test('runNightly: keeps awake for the run, notes a gap, builds indexes before the agent', async () => {
  const v = tmpVault(); const o = opts(v, { keepAwake: true });
  fs.mkdirSync(o.stateDir, { recursive: true });
  const now = new Date(2026, 0, 14, 0, 30);
  fs.writeFileSync(path.join(o.stateDir, 'state.json'), JSON.stringify({ last_success: new Date(2026, 0, 11, 0, 31).toISOString() }));
  const events = [];
  const r = await runNightly(o, {
    now, log: () => {},
    keepAwake: () => { events.push('awake'); return { active: true, stop: () => events.push('stop') }; },
    invoke: async () => {
      events.push('agent');
      assert.ok(fs.existsSync(path.join(v, 'Journal', 'Index - Journal.md')), 'index written before the agent');
      return { code: 0, stdout: 'NIGHTSHIFT_OK 2026-01-13 notes=0 links=0 proposals=0\n', stderr: '' };
    },
  });
  assert.equal(r.status, 'ok');
  assert.deepEqual(events, ['awake', 'agent', 'stop']);
  assert.match(fs.readFileSync(path.join(v, 'Journal', '2026-01-13.md'), 'utf8'), /2 nights missed/);
});
