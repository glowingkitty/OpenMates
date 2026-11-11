#!/usr/bin/env node
// Vercel build entry for the web app (vercel.json buildCommand).
//
// Branches in RUST_CORE_BRANCHES and every production deployment are built with
// the shared Rust client core (VITE_OPENMATES_RUST_CORE=1 plus the wasm package);
// every other build is without it. A production build started from the command
// line carries no branch name, so the production environment counts on its own.
//
// The package is built from source with build-rust-core-web.mjs and kept in the
// build cache together with a digest of every file cargo read for it, so a
// deployment without Rust changes reuses it and any changed input rebuilds it.
// A build that cannot produce the package fails; it never ships a flag-on app
// without its core.
// Plan: docs/plans/client-core-one-core-three-shells/plan.yml (TASK-3)
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const RUST_CORE_BRANCHES = ['dev', 'main'];
const TOOLCHAIN = '1.98.1';
const WASM_BINDGEN_VERSION = '0.2.129';
const WASM_BINDGEN_ARCHIVE = `wasm-bindgen-${WASM_BINDGEN_VERSION}-x86_64-unknown-linux-musl`;
const WASM_BINDGEN_SHA256 = '82d12bb940e2d4e72e0d5605387fc1b8ca179044e012b620f0ce4e7440e8320e';
const PACKAGE_FILES = ['openmates_browser.js', 'openmates_browser_bg.wasm'];
const MANIFEST = 'inputs.json';
const BUILD_SCRIPT = 'frontend/apps/web_app/scripts/build-rust-core-web.mjs';
const SELF = 'frontend/apps/web_app/scripts/vercel-build.mjs';
const DEP_INFO = 'wasm32-unknown-unknown/wasm-web/openmates_browser_bindings.d';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');

/** True when this deployment (a listed branch, or any production build) is built with the Rust client core. */
export function rustCoreBranch(env) {
	return env.VERCEL_ENV === 'production' || RUST_CORE_BRANCHES.includes(env.VERCEL_GIT_COMMIT_REF ?? '');
}

/** Repo-relative source files from a cargo dep-info file (`target: dep dep ...`, spaces escaped). */
export function depInfoFiles(text, repoRoot) {
	const dependencies = text.slice(text.indexOf(': ') + 2).split(/(?<!\\)\s+/).filter(Boolean);
	const files = new Set();
	for (const entry of dependencies) {
		const path = relative(repoRoot, resolve(repoRoot, entry.replaceAll('\\ ', ' ')));
		if (path && !path.startsWith('..')) files.add(path.split(sep).join('/'));
	}
	return [...files].sort();
}

/** Cargo manifests and build inputs that dep-info does not list. */
export function manifestFiles(repoRoot) {
	const files = ['Cargo.toml', 'Cargo.lock', BUILD_SCRIPT, SELF];
	const visit = (directory, depth) => {
		for (const entry of readdirSync(join(repoRoot, directory), { withFileTypes: true })) {
			const path = `${directory}/${entry.name}`;
			if (entry.isFile() && entry.name === 'Cargo.toml') files.push(path);
			if (entry.isDirectory() && depth < 2 && entry.name !== 'target' && entry.name !== 'node_modules') visit(path, depth + 1);
		}
	};
	visit('packages', 0);
	return files.sort();
}

/** Digest of the named input files; null when one of them no longer exists. */
export function inputsDigest(repoRoot, files) {
	const hash = createHash('sha256').update(`${TOOLCHAIN}\n${WASM_BINDGEN_VERSION}\n`);
	for (const file of files) {
		const path = join(repoRoot, file);
		if (!existsSync(path)) return null;
		hash.update(`${file}\n`).update(createHash('sha256').update(readFileSync(path)).digest('hex')).update('\n');
	}
	return hash.digest('hex');
}

/** Relative modules the package entry imports (wasm-bindgen `snippets/`) that are absent from the directory. */
export function missingImports(packageDirectory) {
	const entry = readFileSync(join(packageDirectory, PACKAGE_FILES[0]), 'utf8');
	const imports = [...entry.matchAll(/^import\s[^'"]*['"](\.[^'"]+)['"]/gm)].map((match) => match[1]);
	return imports.filter((path) => !existsSync(join(packageDirectory, path)));
}

/** The cached package directory when its recorded inputs still match the checkout, else null. */
export function cachedPackage(repoRoot, cacheDirectory) {
	const manifestPath = join(cacheDirectory, MANIFEST);
	if (!existsSync(manifestPath) || !PACKAGE_FILES.every((name) => existsSync(join(cacheDirectory, name)))) return null;
	if (missingImports(cacheDirectory).length) return null;
	const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
	return inputsDigest(repoRoot, manifest.files) === manifest.digest ? cacheDirectory : null;
}

/** Records the built package and the inputs it was built from, replacing any older entry. */
export function storePackage(repoRoot, cacheDirectory, builtDirectory, depInfoText) {
	const files = [...new Set([...depInfoFiles(depInfoText, repoRoot), ...manifestFiles(repoRoot)])].sort();
	const digest = inputsDigest(repoRoot, files);
	if (!digest) throw new Error('Rust core package inputs disappeared during the build');
	mkdirSync(dirname(cacheDirectory), { recursive: true });
	const staging = mkdtempSync(join(dirname(cacheDirectory), 'staging-'));
	// The whole output: the entry imports the modules wasm-bindgen writes under snippets/.
	cpSync(builtDirectory, staging, { recursive: true });
	const missing = [...PACKAGE_FILES.filter((name) => !existsSync(join(staging, name))), ...missingImports(staging)];
	if (missing.length) {
		rmSync(staging, { recursive: true, force: true });
		throw new Error(`Rust core package is incomplete: ${missing.join(', ')}`);
	}
	writeFileSync(join(staging, MANIFEST), JSON.stringify({ digest, files }));
	rmSync(cacheDirectory, { recursive: true, force: true });
	renameSync(staging, cacheDirectory);
	return cacheDirectory;
}

function available(command, args, env, expected) {
	try {
		return execFileSync(command, args, { env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).includes(expected);
	} catch (error) {
		if (error.code === 'ENOENT' || typeof error.status === 'number') return false;
		throw error;
	}
}

/** Installs the pinned toolchain and wasm-bindgen when the build machine lacks them; returns the build environment. */
function toolEnvironment(env) {
	const tools = { ...env, RUSTUP_TOOLCHAIN: TOOLCHAIN, PATH: `${join(homedir(), '.cargo/bin')}:${env.PATH}` };
	const run = (command, args) => execFileSync(command, args, { env: tools, stdio: 'inherit' });
	if (!available('rustup', ['--version'], tools, 'rustup')) {
		// Same installer invocation as .github/workflows/rust.yml.
		run('sh', ['-c', "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain none"]);
	}
	run('rustup', ['toolchain', 'install', TOOLCHAIN, '--profile', 'minimal', '--target', 'wasm32-unknown-unknown']);
	if (!available('wasm-bindgen', ['--version'], tools, WASM_BINDGEN_VERSION)) {
		if (process.platform !== 'linux' || process.arch !== 'x64') {
			throw new Error(`Install wasm-bindgen-cli ${WASM_BINDGEN_VERSION}; the pinned download covers x86_64 Linux only`);
		}
		const directory = mkdtempSync(join(tmpdir(), 'wasm-bindgen-'));
		const archive = join(directory, 'wasm-bindgen.tar.gz');
		run('curl', ['--proto', '=https', '--tlsv1.2', '-sSfL', '-o', archive,
			`https://github.com/wasm-bindgen/wasm-bindgen/releases/download/${WASM_BINDGEN_VERSION}/${WASM_BINDGEN_ARCHIVE}.tar.gz`]);
		const actual = createHash('sha256').update(readFileSync(archive)).digest('hex');
		if (actual !== WASM_BINDGEN_SHA256) throw new Error(`wasm-bindgen archive digest mismatch: ${actual}`);
		run('tar', ['-xzf', archive, '-C', directory]);
		tools.PATH = `${join(directory, WASM_BINDGEN_ARCHIVE)}:${tools.PATH}`;
	}
	return tools;
}

/** Returns a package directory for this checkout: the cached one, or a fresh build from source. */
function rustCorePackage(env) {
	const cacheDirectory = join(root, 'frontend/apps/web_app/node_modules/.cache/openmates-rust-core/package');
	const cached = cachedPackage(root, cacheDirectory);
	if (cached) {
		console.log('RUST-CORE-ON: reusing the cached Rust core package (inputs unchanged)');
		return cached;
	}
	console.log('RUST-CORE-ON: building the Rust core package from source (no cached package for these inputs)');
	const tools = toolEnvironment(env);
	const targetDirectory = env.CARGO_TARGET_DIR || join(root, 'target');
	const built = join(targetDirectory, 'web-rust-core-pkg');
	rmSync(built, { recursive: true, force: true });
	execFileSync('node', [join(root, BUILD_SCRIPT), built], { cwd: root, env: tools, stdio: 'inherit' });
	return storePackage(root, cacheDirectory, built, readFileSync(join(targetDirectory, DEP_INFO), 'utf8'));
}

function main() {
	const env = { ...process.env };
	if (rustCoreBranch(env)) {
		env.OPENMATES_RUST_CORE_PKG = rustCorePackage(env);
		env.VITE_OPENMATES_RUST_CORE = '1';
	} else {
		// The branch list is the only switch; a project-level value must not enable half of it.
		delete env.VITE_OPENMATES_RUST_CORE;
		delete env.OPENMATES_RUST_CORE_PKG;
		console.log(`RUST-CORE-OFF: branch "${env.VERCEL_GIT_COMMIT_REF ?? ''}" is not in RUST_CORE_BRANCHES and this is not a production build`);
	}
	execFileSync('pnpm', ['--filter', 'web_app', 'build'], { cwd: root, env, stdio: 'inherit' });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
