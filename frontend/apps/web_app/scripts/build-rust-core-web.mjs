#!/usr/bin/env node
// Builds the shared Rust core browser package for the opt-in web build:
//   node frontend/apps/web_app/scripts/build-rust-core-web.mjs <out-dir> [--wasm-opt]
// then build the web app with OPENMATES_RUST_CORE_PKG=<out-dir> VITE_OPENMATES_RUST_CORE=1.
// Size profile: opt-level z + fat LTO + one codegen unit (about 43% smaller gzip than
// the workspace release profile). wasm-opt -Oz is optional: it shrinks raw bytes ~8%
// but measured ~5% larger gzip/brotli transfer for this module, so it is off by default.
import { execFileSync } from 'node:child_process';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';
import { mkdirSync, readFileSync, renameSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const [outArgument, ...flags] = process.argv.slice(2);
if (!outArgument) {
	console.error('usage: build-rust-core-web.mjs <out-dir> [--wasm-opt]');
	process.exit(2);
}
const out = resolve(outArgument);
const targetDir = process.env.CARGO_TARGET_DIR || join(root, 'target');
const env = {
	...process.env,
	CARGO_PROFILE_RELEASE_OPT_LEVEL: 'z',
	CARGO_PROFILE_RELEASE_LTO: 'fat',
	CARGO_PROFILE_RELEASE_CODEGEN_UNITS: '1'
};
const run = (command, args) => execFileSync(command, args, { cwd: root, env, stdio: 'inherit' });

run('cargo', ['build', '--release', '--locked', '--target', 'wasm32-unknown-unknown', '-p', 'openmates-browser-bindings']);
mkdirSync(out, { recursive: true });
run('wasm-bindgen', ['--target', 'web', '--out-dir', out, '--out-name', 'openmates_browser',
	join(targetDir, 'wasm32-unknown-unknown/release/openmates_browser_bindings.wasm')]);
const wasm = join(out, 'openmates_browser_bg.wasm');
if (flags.includes('--wasm-opt')) {
	run('wasm-opt', ['-Oz', '--enable-bulk-memory', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
		'--enable-mutable-globals', '--enable-reference-types', '--enable-multivalue', wasm, '-o', wasm + '.opt']);
	renameSync(wasm + '.opt', wasm);
}
for (const name of ['openmates_browser.js', 'openmates_browser_bg.wasm']) {
	const bytes = readFileSync(join(out, name));
	const brotli = brotliCompressSync(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: 6 } }).length;
	console.log(`${name}: raw ${bytes.length} gzip ${gzipSync(bytes, { level: 9 }).length} brotli ${brotli}`);
}
