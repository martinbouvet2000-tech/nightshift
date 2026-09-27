#!/usr/bin/env node
// One entry point for the vault tools, so a container has a single ENTRYPOINT
// and a human has one command to remember:
//
//   node vault/entry.mjs audit --strict
//   node vault/entry.mjs fix-links --dry-run
//
// Every tool reads the vault from --vault or NIGHTSHIFT_VAULT, so nothing is
// injected here: the subcommand is mapped to a script and the rest is forwarded
// untouched.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const COMMANDS = Object.freeze({
  audit: 'audit.mjs',
  'fix-links': 'fix-links.mjs',
  normalize: 'normalize.mjs',
  backup: 'backup.mjs',
  write: 'vault-writer.mjs',
});

export function resolveCommand(name) {
  if (!name || name.startsWith('-')) return null;
  return Object.prototype.hasOwnProperty.call(COMMANDS, name) ? COMMANDS[name] : null;
}

export function usage() {
  return [
    'Usage: node vault/entry.mjs <command> [options]',
    '',
    'Commands:',
    ...Object.keys(COMMANDS).map(c => `  ${c}`),
    '',
    'The vault comes from --vault <path> or NIGHTSHIFT_VAULT.',
  ].join('\n');
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('entry.mjs')) {
  const [name, ...rest] = process.argv.slice(2);
  const script = resolveCommand(name);
  if (!script) {
    console.error(name ? `Unknown command: ${name}\n` : '');
    console.error(usage());
    process.exit(2);
  }
  const child = spawn(process.execPath, [path.join(HERE, script), ...rest], { stdio: 'inherit' });
  child.on('exit', code => process.exit(code ?? 1));
  child.on('error', err => { console.error(err.message); process.exit(1); });
}
