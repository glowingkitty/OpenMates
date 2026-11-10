// Engineering test: the Rust core package plugin is a stub unless explicitly packaged.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { rustCoreAssetsPlugin, rustCoreModuleSource, rustCorePackageDirectory } from './vite-plugin-rust-core.mjs';

const directory = mkdtempSync(join(tmpdir(), 'openmates-rust-core-pkg-'));
after(() => rmSync(directory, { recursive: true, force: true }));

test('unset environment resolves the virtual module to a refusing stub', async () => {
	assert.equal(rustCorePackageDirectory({}), null);
	assert.equal(rustCorePackageDirectory({ OPENMATES_RUST_CORE_PKG: '  ' }), null);
	const plugin = rustCoreAssetsPlugin({});
	const id = plugin.resolveId('virtual:openmates-rust-core-package');
	assert.equal(plugin.resolveId('some-other-module'), null);
	const source = plugin.load(id);
	assert.match(source, /export const artifact = null;/);
	assert.match(source, /rust_core_assets_disabled/);
	assert.doesNotMatch(source, /import /);
});

test('a package directory without wasm-bindgen output is refused', () => {
	assert.throws(() => rustCoreModuleSource(directory), /must contain/);
});

test('a packaged core exposes its WASM digest and lazy loader', () => {
	const wasm = Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]);
	writeFileSync(join(directory, 'openmates_browser.js'), 'export default async function init() {}\n');
	writeFileSync(join(directory, 'openmates_browser_bg.wasm'), wasm);
	const source = rustCoreModuleSource(directory);
	assert.match(source, new RegExp(`artifact = "${createHash('sha256').update(wasm).digest('hex')}"`));
	assert.match(source, /openmates_browser_bg\.wasm\?url/);
	assert.match(source, /export function loadBinding\(\)/);
	assert.match(source, /openmates:rust:wasm-instantiate-start/);
	assert.match(source, /__openmatesRustCoreWasmBytes/);
});

test('a flag-on production build without the package is refused before bundling', () => {
	const flagOnly = rustCoreAssetsPlugin({ VITE_OPENMATES_RUST_CORE: '1' });
	assert.throws(() => flagOnly.config({}, { command: 'build' }), /requires OPENMATES_RUST_CORE_PKG/);
	assert.doesNotThrow(() => flagOnly.config({}, { command: 'serve' }));
	assert.doesNotThrow(() => rustCoreAssetsPlugin({}).config({}, { command: 'build' }));
	assert.doesNotThrow(() =>
		rustCoreAssetsPlugin({ VITE_OPENMATES_RUST_CORE: '1', OPENMATES_RUST_CORE_PKG: directory }).config({}, { command: 'build' })
	);
});
