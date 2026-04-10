/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared CLI test helpers for Playwright E2E tests.
 *
 * Extracted from cli-skills-apps.spec.ts.
 * Provides CLI process spawning and API URL derivation.
 *
 * Usage:
 *   const { runCli, deriveApiUrl, CLI_DIST } = require('./helpers/cli-test-helpers');
 *
 * Architecture context: docs/architecture/openmates-cli.md
 */
export {};

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../../packages/openmates-cli/dist/cli.js');

/**
 * Derive the API URL from the Playwright base URL.
 * Supports openmates.org, app.* subdomains, and localhost.
 */
function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org')
			return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		/* fall through */
	}
	return 'https://api.openmates.org';
}

/**
 * Spawn the CLI with API key auth and return stdout/stderr/exit code.
 * Automatically prepends --api-key if OPENMATES_TEST_ACCOUNT_API_KEY is set.
 */
async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 30_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	const apiKey = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	const allArgs = apiKey ? ['--api-key', apiKey, ...args] : args;

	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...allArgs], {
			env: {
				...process.env,
				OPENMATES_API_URL: apiUrl,
				NODE_PATH: path.join(cliDir, 'node_modules')
			},
			stdio: ['pipe', 'pipe', 'pipe']
		});
		const out: string[] = [];
		const err: string[] = [];
		child.stdout.on('data', (d: Buffer) => out.push(d.toString()));
		child.stderr.on('data', (d: Buffer) => err.push(d.toString()));
		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: out.join(''), stderr: err.join('') });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: out.join(''), stderr: err.join('') });
		});
	});
}

/**
 * Parse CLI JSON output and validate the success envelope.
 * Throws with helpful error if parsing or validation fails.
 */
function parseCliJson(result: { code: number | null; stdout: string; stderr: string }): any {
	let parsed: any;
	try {
		parsed = JSON.parse(result.stdout);
	} catch (e) {
		throw new Error(`Expected JSON output, got:\n${result.stdout}\nstderr:\n${result.stderr}`);
	}
	return parsed;
}

/**
 * Assert CLI exited with code 0 and attach stderr/stdout to the failure
 * message so CI reports show the actual error instead of a bare "Expected: 0".
 *
 * Playwright's expect(value, message) puts the message in the test report
 * when the assertion fails — this is the cheapest way to surface CLI errors.
 */
function expectCliSuccess(
	result: { code: number | null; stdout: string; stderr: string },
	label = 'CLI'
): void {
	const { expect } = require('@playwright/test');
	const truncStdout = result.stdout.length > 1000
		? result.stdout.slice(0, 1000) + `\n…(truncated, ${result.stdout.length} chars total)`
		: result.stdout;
	expect(
		result.code,
		`${label} exited with code ${result.code}\n` +
		`── stderr ──\n${result.stderr || '(empty)'}\n` +
		`── stdout ──\n${truncStdout || '(empty)'}`
	).toBe(0);
}

module.exports = {
	CLI_DIST,
	deriveApiUrl,
	runCli,
	parseCliJson,
	expectCliSuccess
};
