#!/usr/bin/env node
// Builds the shared Rust core browser package for the opt-in web build:
//   node frontend/apps/web_app/scripts/build-rust-core-web.mjs <out-dir> [--wasm-opt]
// then build the web app with OPENMATES_RUST_CORE_PKG=<out-dir> VITE_OPENMATES_RUST_CORE=1.
// Profile `wasm-web` (root Cargo.toml): opt-level z + fat LTO + one codegen unit,
// with opt-level 3 for the crypto crates the shared Worker crypto unit runs per
// message, plus simd128 (~13% faster AES-GCM, no size cost; see Cargo.toml).
// wasm-opt -Oz is optional: it shrinks raw bytes but measured larger gzip/brotli
// transfer for this module, so it is off by default.
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
const PROFILE = 'wasm-web';
// WASM SIMD (simd128) lets LLVM vectorize the software AES-GCM; every supported
// browser runs it (Chrome 91, Firefox 89, Safari 16.4).
const SIMD = true;
const env = {
	...process.env,
	...(SIMD ? { RUSTFLAGS: [process.env.RUSTFLAGS, '-C target-feature=+simd128'].filter(Boolean).join(' ') } : {})
};
const run = (command, args) => execFileSync(command, args, { cwd: root, env, stdio: 'inherit' });

run('cargo', ['build', '--profile', PROFILE, '--locked', '--target', 'wasm32-unknown-unknown', '-p', 'openmates-browser-bindings']);
mkdirSync(out, { recursive: true });
run('wasm-bindgen', ['--target', 'web', '--out-dir', out, '--out-name', 'openmates_browser',
	join(targetDir, `wasm32-unknown-unknown/${PROFILE}/openmates_browser_bindings.wasm`)]);
const wasm = join(out, 'openmates_browser_bg.wasm');
if (flags.includes('--wasm-opt')) {
	run('wasm-opt', ['-Oz', ...(SIMD ? ['--enable-simd'] : []), '--enable-bulk-memory', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
		'--enable-mutable-globals', '--enable-reference-types', '--enable-multivalue', wasm, '-o', wasm + '.opt']);
	renameSync(wasm + '.opt', wasm);
}
for (const name of ['openmates_browser.js', 'openmates_browser_bg.wasm']) {
	const bytes = readFileSync(join(out, name));
	const brotli = brotliCompressSync(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: 6 } }).length;
	console.log(`${name}: raw ${bytes.length} gzip ${gzipSync(bytes, { level: 9 }).length} brotli ${brotli}`);
}
