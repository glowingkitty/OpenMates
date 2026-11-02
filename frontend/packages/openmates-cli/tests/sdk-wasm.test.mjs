/** Portable WASM loader: explicit package-relative artifact, typed refusal when absent. */
// contract-test-file: tooling
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const artifact = path.join(root, 'wasm', 'openmates_sdk_bg.wasm');

// Emit only src/sdkWasm.ts into an isolated package layout (dist/ + wasm/), so the
// loader resolves its artifact exactly as the published package does.
async function isolatedLoader(withArtifact) {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-sdk-wasm-'));
  fs.mkdirSync(path.join(fixture, 'dist'));
  const source = fs.readFileSync(path.join(root, 'src', 'sdkWasm.ts'), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  fs.writeFileSync(path.join(fixture, 'dist', 'sdkWasm.mjs'), output.outputText);
  if (withArtifact) fs.cpSync(path.join(root, 'wasm'), path.join(fixture, 'wasm'), { recursive: true });
  const module = await import(pathToFileURL(path.join(fixture, 'dist', 'sdkWasm.mjs')).href);
  return { fixture, loadSdkWasm: module.loadSdkWasm };
}

test('missing WASM artifact yields no module (callers raise native_binding_unavailable)', async () => {
  const { fixture, loadSdkWasm } = await isolatedLoader(false);
  try { assert.equal(loadSdkWasm(), null); } finally { fs.rmSync(fixture, { recursive: true, force: true }); }
});

test('packaged WASM artifact runs the shared privacy and task-order core', { skip: !fs.existsSync(artifact) && 'build with npm run build:sdk:wasm' }, async () => {
  const { fixture, loadSdkWasm } = await isolatedLoader(true);
  try {
    const wasm = loadSdkWasm();
    assert.ok(wasm);
    const prepared = JSON.parse(wasm.privacy(JSON.stringify({ operation: 'prepare', text: 'mail fictional@example.invalid', memories: [], existing_mappings: [], enhanced: false })));
    assert.ok(!prepared.text.includes('fictional@example.invalid'));
    const restored = JSON.parse(wasm.privacy(JSON.stringify({ operation: 'restore', text: prepared.text, mappings: prepared.mappings })));
    assert.equal(restored.text, 'mail fictional@example.invalid');
    // Errors keep the shared fixed JSON envelope used by every binding.
    assert.throws(() => wasm.taskOrder('{"rows":[],"locale":""}'), (error) => {
      const value = JSON.parse(error.message);
      return value.code === 'invalid_argument' && typeof value.message === 'string';
    });
  } finally { fs.rmSync(fixture, { recursive: true, force: true }); }
});
