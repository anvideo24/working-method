#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const required = ['AGENTS.md', 'HOW.md', 'LESSONS.md', 'RULES.md'];
const linkPattern = /!?(?:\[[^\]]*\])\(\s*(<[^>]+>|[^\s)]+)(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)/g;

function hasConflictMarker(content) {
  for (const line of content.split(/\r?\n/)) {
    if (/^<<<<<<<(?: |$)/.test(line) || /^>>>>>>>(?: |$)/.test(line)) return true;
  }
  return false;
}

function trackedMarkdown(root) {
  const output = execFileSync('git', ['-C', root, 'ls-files', '-z', '--', '*.md'], { encoding: 'utf8' });
  return output.split('\0').filter(Boolean);
}

export function checkDocs(root) {
  const errors = [];
  for (const file of required) {
    if (!fs.existsSync(path.join(root, file))) errors.push(`missing required document: ${file}`);
  }
  for (const relative of trackedMarkdown(root)) {
    const file = path.join(root, relative);
    if (!fs.existsSync(file)) continue;
    const content = fs.readFileSync(file, 'utf8');
    if (!content.trim()) errors.push(`empty document: ${relative}`);
    if (hasConflictMarker(content)) errors.push(`conflict marker: ${relative}`);
    for (const match of content.matchAll(linkPattern)) {
      const rawTarget = match[1].replace(/^<|>$/g, '').trim().split(/[?#]/, 1)[0];
      if (!rawTarget || rawTarget.startsWith('/') || /^[a-z][a-z\d+.-]*:/i.test(rawTarget)) continue;
      let target;
      try {
        target = decodeURIComponent(rawTarget);
      } catch {
        errors.push(`invalid encoded relative link: ${relative}`);
        continue;
      }
      const resolved = path.resolve(path.dirname(file), target);
      const relativeToRoot = path.relative(root, resolved);
      if (relativeToRoot === '..' || relativeToRoot.startsWith('..' + path.sep) || path.isAbsolute(relativeToRoot)) {
        errors.push(`relative link escapes repository: ${relative}`);
      } else if (!fs.existsSync(resolved)) {
        errors.push(`missing relative link: ${relative} -> ${target}`);
      }
    }
  }
  return errors;
}

function selfTest() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'working-method-docs-'));
  const resolvedRoot = path.resolve(root);
  const tempRoot = path.resolve(os.tmpdir());
  assert.equal(resolvedRoot.startsWith(tempRoot + path.sep), true);
  try {
    execFileSync('git', ['init', '-q', root]);
    for (const file of required) fs.writeFileSync(path.join(root, file), `# ${file}\n`);
    fs.mkdirSync(path.join(root, 'nested'));
    fs.writeFileSync(path.join(root, 'nested', 'space file.md'), '# nested\n');
    fs.writeFileSync(path.join(root, 'guide.md'), '[rules](HOW.md "title") [nested](nested/space%20file.md) [external](https://example.com/100%)\n');
    execFileSync('git', ['-C', root, 'add', '.']);
    assert.deepEqual(checkDocs(root), []);
    fs.writeFileSync(path.join(root, 'bad.md'), '<<<<<<< ours\n[rules](missing.md)\n');
    fs.writeFileSync(path.join(root, 'escape.md'), '[outside](../outside.md)\n');
    execFileSync('git', ['-C', root, 'add', 'bad.md', 'escape.md']);
    assert.deepEqual(checkDocs(root), ['conflict marker: bad.md', 'missing relative link: bad.md -> missing.md', 'relative link escapes repository: escape.md']);
    fs.writeFileSync(path.join(root, 'nested', 'space file.md'), '');
    assert.equal(checkDocs(root).includes('empty document: nested/space file.md'), true);
    fs.rmSync(path.join(root, 'AGENTS.md'));
    assert.equal(checkDocs(root).includes('missing required document: AGENTS.md'), true);
    fs.writeFileSync(path.join(root, 'HOW.md'), '');
    execFileSync('git', ['-C', root, 'add', 'HOW.md']);
    assert.equal(checkDocs(root).includes('empty document: HOW.md'), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

if (process.argv[2] === '--self-test') {
  selfTest();
  console.log('docs self-test passed');
} else {
  const errors = checkDocs(process.cwd());
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exitCode = 1;
  } else console.log('docs check passed');
}
