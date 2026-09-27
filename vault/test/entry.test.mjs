import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { COMMANDS, resolveCommand, usage } from '../entry.mjs';

const VAULT_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

test('every mapped command points at a script that exists', () => {
  for (const [name, script] of Object.entries(COMMANDS)) {
    assert.ok(fs.existsSync(path.join(VAULT_DIR, script)), `${name} -> ${script} missing`);
  }
});

test('known commands resolve', () => {
  assert.equal(resolveCommand('audit'), 'audit.mjs');
  assert.equal(resolveCommand('fix-links'), 'fix-links.mjs');
});

test('unknown, empty and flag-like names resolve to nothing', () => {
  for (const bad of ['nope', '', undefined, '--help', '-h']) {
    assert.equal(resolveCommand(bad), null, `${JSON.stringify(bad)} should not resolve`);
  }
});

test('inherited object properties are not commands', () => {
  // COMMANDS['constructor'] would otherwise hand back a function.
  for (const bad of ['constructor', 'toString', '__proto__']) {
    assert.equal(resolveCommand(bad), null);
  }
});

test('usage lists every command', () => {
  const text = usage();
  for (const name of Object.keys(COMMANDS)) assert.ok(text.includes(name), `${name} missing`);
});
