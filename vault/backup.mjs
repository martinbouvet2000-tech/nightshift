#!/usr/bin/env node
// backup.mjs — commit and push the vault if it is a git repository. Cross-platform, never blocking.
//  - not a git repo           -> skip cleanly (exit 0)
//  - maintenance lock present -> skip (a mass edit is in progress; avoid snapshotting half a migration)
//  - changes                  -> git add -A + commit
//  - remote configured        -> pull --rebase, then push. On a rebase conflict the rebase is aborted
//                                and the push skipped: the local commit is kept, nothing is overwritten.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseArgs, resolveVault, loadConfig, isMain } from './lib.mjs';

const HELP = `backup — git add/commit/push of the vault (skips cleanly when not a git repo)

Usage: node backup.mjs [--vault <path>] [--reason <text>] [--no-push] [--dry-run]`;

export function makeGit(cwd) {
  return (...args) => {
    const r = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
    return { code: r.status ?? 1, out: (r.stdout || '').trim(), err: (r.stderr || r.error?.message || '').trim() };
  };
}

export function backup(vault, config, { reason = 'manual', push = true, dryRun = false, git = makeGit(vault), log = console.log } = {}) {
  if (!fs.existsSync(path.join(vault, '.git'))) { log('skip: vault is not a git repository'); return { status: 'skipped-not-git' }; }
  if (fs.existsSync(path.join(vault, config.maintenanceLock))) { log('skip: maintenance lock present'); return { status: 'skipped-locked' }; }
  const st = git('status', '--porcelain');
  if (st.code !== 0) { log(`error: git status failed: ${st.err}`); return { status: 'error' }; }
  const changes = st.out ? st.out.split('\n').length : 0;
  const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
  if (dryRun) { log(`dry-run: would commit ${changes} change(s) and ${push ? 'push' : 'not push'}`); return { status: 'dry-run', changes }; }
  if (changes > 0) {
    git('add', '-A');
    const c = git('commit', '-q', '-m', `vault backup ${stamp} (${reason}) - ${changes} file(s)`);
    if (c.code !== 0) { log(`error: commit failed: ${c.err || c.out}`); return { status: 'error', changes }; }
    log(`committed ${changes} file(s)`);
  } else log('nothing to commit');
  if (!push) return { status: 'committed', changes };
  if (!git('remote').out) { log('no remote configured: local commit only'); return { status: 'local-only', changes }; }
  const branch = git('rev-parse', '--abbrev-ref', 'HEAD').out || 'HEAD';
  const hasUpstream = git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}').code === 0;
  if (hasUpstream) {
    const p = git('pull', '--rebase', '-q');
    if (p.code !== 0) {
      git('rebase', '--abort');
      log(`warning: pull --rebase failed, rebase aborted, push skipped (resolve manually): ${p.err}`);
      return { status: 'conflict', changes };
    }
  }
  const r = hasUpstream ? git('push', '-q') : git('push', '-q', '-u', 'origin', branch);
  if (r.code !== 0) { log(`warning: push failed (network?), will retry next run: ${r.err}`); return { status: 'push-failed', changes }; }
  log('pushed');
  return { status: 'pushed', changes };
}

function main(argv) {
  const { flags } = parseArgs(argv, ['no-push', 'dry-run', 'help']);
  if (flags.help) { console.log(HELP); return 0; }
  const vault = resolveVault(flags);
  const config = loadConfig(vault, flags);
  const r = backup(vault, config, { reason: typeof flags.reason === 'string' ? flags.reason : 'manual', push: !flags['no-push'], dryRun: !!flags['dry-run'] });
  return r.status === 'error' ? 1 : 0;
}

if (await isMain(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`error: ${e.message}`); process.exitCode = 1; }
}
