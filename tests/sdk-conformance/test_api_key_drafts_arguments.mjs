/** Inert regression for the exact no-root coordinator argv; no SDK import/IO. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Script, createContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
const runnerUrl = new URL('./runners/api-key-drafts.mjs', import.meta.url);
const source = readFileSync(runnerUrl, 'utf8');
const start = source.indexOf('// argument-parser-start');
const end = source.indexOf('// argument-parser-end');
assert.ok(start >= 0 && end > start);
const parser = source.slice(start, end);
function parse(args) {
  const context = createContext({ assert, args });
  return new Script(parser + '\nparseArguments(args)').runInContext(context);
}
const gateArgs = ['--fixture', 'tests/sdk-conformance/fixtures/sdk-api-key-drafts.json', '--capability', 'sdk.drafts'];
const parsed = parse(gateArgs);
assert.equal(parsed.root, undefined);
assert.equal(parsed.fixture, gateArgs[1]);
assert.equal(parsed.capability, 'sdk.drafts');
const expectedRoot = fileURLToPath(new URL('../../', import.meta.url));
const selectedRoot = parsed.root ?? fileURLToPath(new URL('../../..', runnerUrl));
assert.equal(selectedRoot.replace(/\/$/, ''), expectedRoot.replace(/\/$/, ''));
assert.equal(parse([...gateArgs, '--root', '/synthetic/repo']).root, '/synthetic/repo');
for (const args of [[], ['--fixture'], [...gateArgs, '--root'], [...gateArgs, '--root', '--fixture'], [...gateArgs, '--root', '/one', '--root', '/two'], [...gateArgs, '--unknown', 'x'], ['--fixture', 'x', '--capability', 'other']]) {
  assert.throws(() => parse(args));
}
console.log(JSON.stringify({ check: 'draft adapter exact gate argv and default root', status: 'passed', negativeCases: 7 }));
