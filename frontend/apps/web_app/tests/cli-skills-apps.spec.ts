/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * CLI App Skills E2E Tests
 *
 * Tests executing app skills directly via the CLI `openmates apps <app> <skill>` command.
 * Covers skills that are accessible via the REST API and testable without a user-session
 * encryption context (no embed decryption required).
 *
 * Tested skills:
 *   - web/search      — Brave web search
 *   - web/read        — Firecrawl web reader
 *   - math/calculate  — sympy/mpmath numeric computation (JSON output test)
 *   - events/search   — Meetup + Luma event aggregation
 *
 * These tests use the `--api-key` flag instead of pair-auth login, which
 * is faster and avoids the browser pairing flow for pure REST-callable skills.
 * The API key is read from OPENMATES_TEST_ACCOUNT_API_KEY env var.
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 *
 * REQUIRED ENV VARS:
 *   - OPENMATES_TEST_ACCOUNT_API_KEY
 *   - PLAYWRIGHT_TEST_BASE_URL
 *
 * Execution:
 *   npx playwright test frontend/apps/web_app/tests/cli-skills-apps.spec.ts
 */

const { test, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

// ---------------------------------------------------------------------------
// Derive API URL from Playwright base URL
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// runCli helper — spawn CLI with API key auth (no browser session required)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('CLI App Skills', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		apiUrl = deriveApiUrl(baseUrl);
	});

	// -------------------------------------------------------------------------
	// web/search
	// -------------------------------------------------------------------------

	test('web/search returns results for a basic query', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(apiUrl, ['apps', 'web', 'search', 'OpenMates AI assistant']);
		expect(result.code).toBe(0);
		// Human-readable output should contain at least one URL or result title
		expect(result.stdout.length).toBeGreaterThan(10);
		expect(result.stderr).not.toMatch(/error|failed|exception/i);
	});

	// -------------------------------------------------------------------------
	// web/read — JSON output test (required: verifies --json flag works)
	// -------------------------------------------------------------------------

	test('web/read returns structured JSON output with --json flag', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps',
				'web',
				'read',
				'--input',
				JSON.stringify({ requests: [{ url: 'https://example.com' }] }),
				'--json'
			],
			30_000
		);

		expect(result.code).toBe(0);

		// --json must produce valid parseable JSON
		let parsed: any;
		try {
			parsed = JSON.parse(result.stdout);
		} catch (e) {
			throw new Error(`Expected JSON output, got:\n${result.stdout}\nstderr:\n${result.stderr}`);
		}

		// Outer skill response envelope
		expect(parsed.success).toBe(true);
		expect(parsed.data).toBeTruthy();
		const skillData = parsed.data;

		// web/read returns a 'results' array with page objects
		expect(Array.isArray(skillData.results)).toBe(true);
		expect(skillData.results.length).toBeGreaterThan(0);

		const resultGroup = skillData.results[0];
		expect(Array.isArray(resultGroup.results)).toBe(true);
		const page = resultGroup.results[0];

		expect(page.url).toContain('example.com');
		expect(page.title).toBeTruthy();
		expect(typeof page.markdown).toBe('string');
		expect(page.markdown.length).toBeGreaterThan(20);

		console.log(`[web/read] title="${page.title}", markdown length=${page.markdown.length}`);
	});

	// -------------------------------------------------------------------------
	// math/calculate — JSON output test (verifies --json + numeric result)
	// -------------------------------------------------------------------------

	test('math/calculate returns correct numeric result as JSON', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps',
				'math',
				'calculate',
				'--input',
				JSON.stringify({ expression: 'sqrt(144)', mode: 'numeric', precision: 10 }),
				'--json'
			],
			25_000
		);

		expect(result.code).toBe(0);

		// Must be valid JSON
		let parsed: any;
		try {
			parsed = JSON.parse(result.stdout);
		} catch (e) {
			throw new Error(`Expected JSON output, got:\n${result.stdout}\nstderr:\n${result.stderr}`);
		}

		expect(parsed.success).toBe(true);
		const skillData = parsed.data;
		const results = skillData.results || [];
		expect(results.length).toBeGreaterThan(0);

		const item = (results[0].results || [])[0];
		expect(item).toBeTruthy();

		// sqrt(144) = 12 exactly
		const resultStr = String(item.result || '');
		expect(resultStr).toMatch(/^12(\.0*)?$/);

		console.log(`[math/calculate] sqrt(144) = ${item.result} (mode=${item.mode})`);
	});

	// -------------------------------------------------------------------------
	// events/search — verify provider field in JSON output
	// -------------------------------------------------------------------------

	test('events/search returns Berlin tech events as JSON', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps',
				'events',
				'search',
				'--input',
				JSON.stringify({
					requests: [
						{
							query: 'technology meetup',
							location: 'Berlin',
							provider: 'auto'
						}
					]
				}),
				'--json'
			],
			45_000
		);

		expect(result.code).toBe(0);

		let parsed: any;
		try {
			parsed = JSON.parse(result.stdout);
		} catch (e) {
			throw new Error(`Expected JSON output, got:\n${result.stdout}\nstderr:\n${result.stderr}`);
		}

		expect(parsed.success).toBe(true);
		const skillData = parsed.data;
		expect(Array.isArray(skillData.results)).toBe(true);
		expect(skillData.results.length).toBeGreaterThan(0);

		const events = skillData.results[0].results || [];
		expect(events.length).toBeGreaterThan(0);

		const ev = events[0];
		expect(ev.name || ev.title).toBeTruthy();
		expect(ev.url).toBeTruthy();

		console.log(`[events/search] Found ${events.length} event(s). First: "${ev.name || ev.title}"`);
	});
});
