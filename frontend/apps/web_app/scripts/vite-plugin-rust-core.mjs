// Build-time packaging of the shared Rust core (wasm-bindgen `--target web` output)
// for the opt-in shared browser Worker (src/lib/rustCore/shared/shared.worker.ts).
//
// Inert unless OPENMATES_RUST_CORE_PKG names a package directory: the virtual
// module then resolves to a stub whose loadBinding() refuses, and nothing in the
// default app imports it. Build the package with
// `node frontend/apps/web_app/scripts/build-rust-core-web.mjs <out-dir>`.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const VIRTUAL = 'virtual:openmates-rust-core-package';
const INTERNAL = '\0' + VIRTUAL;
const JAVASCRIPT = 'openmates_browser.js';
const WASM = 'openmates_browser_bg.wasm';

const STUB =
	'export const artifact = null;\n' +
	'export const assets = null;\n' +
	'export async function loadBinding() { throw new Error("rust_core_assets_disabled"); }\n';

/** Absolute package directory from the environment, or null when the core is not packaged. */
export function rustCorePackageDirectory(env = process.env) {
	const directory = env.OPENMATES_RUST_CORE_PKG?.trim();
	return directory ? resolve(directory) : null;
}

/** Source of the virtual module for a package directory (or the stub for null). */
export function rustCoreModuleSource(directory) {
	if (!directory) return STUB;
	const javascript = resolve(directory, JAVASCRIPT);
	const wasm = resolve(directory, WASM);
	if (!existsSync(javascript) || !existsSync(wasm)) {
		throw new Error(`OPENMATES_RUST_CORE_PKG must contain ${JAVASCRIPT} and ${WASM}`);
	}
	// Identifies the exact core build; the Worker bootstrap echoes it back.
	const artifact = createHash('sha256').update(readFileSync(wasm)).digest('hex');
	return [
		`import init, * as binding from ${JSON.stringify(javascript)};`,
		`import wasmUrl from ${JSON.stringify(wasm + '?url')};`,
		`export const artifact = ${JSON.stringify(artifact)};`,
		'export const assets = Object.freeze({ artifact, javascriptUrl: import.meta.url, wasmUrl });',
		'let loading = null;',
		'export function loadBinding() {',
		'\tloading ??= init({ module_or_path: wasmUrl }).then(() => binding);',
		'\treturn loading;',
		'}',
		''
	].join('\n');
}

export function rustCoreAssetsPlugin(env = process.env) {
	const directory = rustCorePackageDirectory(env);
	return {
		name: 'openmates-rust-core-package',
		resolveId(id) {
			return id === VIRTUAL ? INTERNAL : null;
		},
		load(id) {
			return id === INTERNAL ? rustCoreModuleSource(directory) : null;
		}
	};
}
