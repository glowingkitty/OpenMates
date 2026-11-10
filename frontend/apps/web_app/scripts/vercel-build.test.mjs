// Engineering test: the Vercel build entry reuses a Rust core package only while
// every recorded input is unchanged, and only listed branches build with the core.
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { cachedPackage, depInfoFiles, manifestFiles, rustCoreBranch, RUST_CORE_BRANCHES, storePackage } from './vercel-build.mjs';

const repo = mkdtempSync(join(tmpdir(), 'openmates-vercel-build-'));
after(() => rmSync(repo, { recursive: true, force: true }));

const write = (path, content) => {
	mkdirSync(join(repo, path, '..'), { recursive: true });
	writeFileSync(join(repo, path), content);
};
write('Cargo.toml', '[workspace]\n');
write('Cargo.lock', 'version = 4\n');
write('packages/core/Cargo.toml', '[package]\n');
write('packages/core/src/lib.rs', 'pub fn a() {}\n');
write('packages/core/src/data file.json', '{}\n');
write('packages/third_party/dep/Cargo.toml', '[package]\n');
write('packages/core/target/Cargo.toml', 'ignored\n');
write('frontend/apps/web_app/scripts/build-rust-core-web.mjs', '// build\n');
write('frontend/apps/web_app/scripts/vercel-build.mjs', '// entry\n');
write('built/openmates_browser.js', 'export default 1;\n');
write('built/openmates_browser_bg.wasm', 'wasm');

const depInfo = `${repo}/target/out.wasm: ${repo}/packages/core/src/lib.rs ${repo}/packages/core/src/data\\ file.json /outside/registry/dep.rs\n`;
const cache = join(repo, 'cache/package');

test('only listed branches build with the Rust core', () => {
	assert.deepEqual(RUST_CORE_BRANCHES, ['dev']);
	assert.equal(rustCoreBranch({ VERCEL_GIT_COMMIT_REF: 'dev' }), true);
	assert.equal(rustCoreBranch({ VERCEL_GIT_COMMIT_REF: 'main' }), false);
	assert.equal(rustCoreBranch({}), false);
});

test('dep-info yields repo-relative files, keeps escaped spaces and drops outside paths', () => {
	assert.deepEqual(depInfoFiles(depInfo, repo), ['packages/core/src/data file.json', 'packages/core/src/lib.rs']);
});

test('manifests include workspace and patched crates but not build output', () => {
	assert.deepEqual(manifestFiles(repo), [
		'Cargo.lock',
		'Cargo.toml',
		'frontend/apps/web_app/scripts/build-rust-core-web.mjs',
		'frontend/apps/web_app/scripts/vercel-build.mjs',
		'packages/core/Cargo.toml',
		'packages/third_party/dep/Cargo.toml'
	]);
});

test('a stored package is reused until any recorded input changes or disappears', () => {
	assert.equal(cachedPackage(repo, cache), null);
	assert.equal(storePackage(repo, cache, join(repo, 'built'), depInfo), cache);
	assert.equal(cachedPackage(repo, cache), cache);

	write('packages/core/src/data file.json', '{"changed":true}\n');
	assert.equal(cachedPackage(repo, cache), null);
	storePackage(repo, cache, join(repo, 'built'), depInfo);
	assert.equal(cachedPackage(repo, cache), cache);

	write('Cargo.lock', 'version = 4\n# bumped\n');
	assert.equal(cachedPackage(repo, cache), null);
	storePackage(repo, cache, join(repo, 'built'), depInfo);

	rmSync(join(repo, 'packages/core/src/lib.rs'));
	assert.equal(cachedPackage(repo, cache), null);
});

test('a cache entry without the wasm file is not reused', () => {
	write('packages/core/src/lib.rs', 'pub fn a() {}\n');
	storePackage(repo, cache, join(repo, 'built'), depInfo);
	rmSync(join(cache, 'openmates_browser_bg.wasm'));
	assert.equal(cachedPackage(repo, cache), null);
});
