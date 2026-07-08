#!/usr/bin/env node

/**
 * Build the SvelteKit static bundle used by the internal VS Code extension.
 *
 * The VS Code bundle uses adapter-static and only needs the generated files in
 * `build/`. Some SSR-imported app services keep Node alive after adapter-static
 * has written the fallback page, so this wrapper treats that marker as success
 * and terminates the lingering Vite process before CI reaches the heap limit.
 */

import { spawn } from 'node:child_process';

const STATIC_FALLBACK_MARKER = 'Overwriting build/index.html with fallback page';
const TERMINATE_AFTER_SUCCESS_MS = 1000;
const FORCE_KILL_AFTER_MS = 5000;
const BUILD_TIMEOUT_MS = 8 * 60 * 1000;

const child = spawn('vite', ['build'], {
	stdio: ['ignore', 'pipe', 'pipe'],
	env: {
		...process.env,
		OPENMATES_BUILD_TARGET: 'vscode'
	}
});

let sawStaticBundleSuccess = false;
let terminationRequested = false;

function relayAndInspect(stream, target) {
	stream.on('data', (chunk) => {
		const text = chunk.toString();
		target.write(chunk);

		if (!sawStaticBundleSuccess && text.includes(STATIC_FALLBACK_MARKER)) {
			sawStaticBundleSuccess = true;
			setTimeout(() => {
				if (child.exitCode === null) {
					terminationRequested = true;
					child.kill('SIGTERM');
					setTimeout(() => {
						if (child.exitCode === null) {
							child.kill('SIGKILL');
						}
					}, FORCE_KILL_AFTER_MS).unref();
				}
			}, TERMINATE_AFTER_SUCCESS_MS).unref();
		}
	});
}

relayAndInspect(child.stdout, process.stdout);
relayAndInspect(child.stderr, process.stderr);

const timeout = setTimeout(() => {
	console.error('VS Code web app build timed out before adapter-static finished.');
	terminationRequested = true;
	child.kill('SIGTERM');
	setTimeout(() => {
		if (child.exitCode === null) {
			child.kill('SIGKILL');
		}
	}, FORCE_KILL_AFTER_MS).unref();
}, BUILD_TIMEOUT_MS);

child.on('error', (error) => {
	clearTimeout(timeout);
	console.error(`Failed to start Vite build: ${error.message}`);
	process.exit(1);
});

child.on('close', (code) => {
	clearTimeout(timeout);
	if (code === 0 || (sawStaticBundleSuccess && terminationRequested)) {
		process.exit(0);
	}

	console.error(`VS Code web app build failed with exit code ${code}.`);
	process.exit(code ?? 1);
});
