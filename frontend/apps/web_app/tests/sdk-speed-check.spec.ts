/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (headless SDK benchmark; no UI involved)
/**
 * Cross-SDK speed check against the disposable isolated backend with the fresh
 * account's API key (no mocks): the Rust `openmates::sdk`, npm (the maintained
 * TypeScript API-key implementation, i.e. the TypeScript reference) and Python
 * SDKs run the same drafts/wikipedia operations through
 * tests/sdk-conformance/benchmark_sdk_speed.py. Drafts are seeded through the
 * owner's first-party CLI session so decryption does real work. The report is
 * attached; the spec fails on functional SDK differences or on a gross Rust
 * regression (>25% AND >100 ms, or a leak) under the advisory perf policy.
 */
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const TOOLCHAIN = '1.98.1';
const DEVICE_PREFIX = 'sdk-speed-e2e';
const ACCESS: Record<string, string> = { rust: 'rust', npm: 'npm', python: 'pip' };

function run(command: string, args: string[], options: { env?: Record<string, string>; input?: string; timeout?: number }, label: string) {
	const result = spawnSync(command, args, {
		cwd: ROOT,
		env: { ...process.env, ...(options.env ?? {}) },
		input: options.input,
		encoding: 'utf8',
		timeout: options.timeout ?? 150_000,
		maxBuffer: 64 * 1024 * 1024
	});
	return { label, status: result.status, stdout: String(result.stdout || ''), stderr: String(result.stderr || ''), error: result.error };
}

function mustRun(command: string, args: string[], options: Parameters<typeof run>[2], label: string) {
	const result = run(command, args, options, label);
	expect(result.status, `${label} exited ${result.status ?? result.error?.code} :: ${result.stderr.slice(-3000)}`).toBe(0);
	return result.stdout;
}

/** Owner-session program run through the subject CLI build's first-party client. */
function ownerProgram(apiUrl: string, body: string, env: Record<string, string>, label: string): any {
	const program = `import { OpenMatesClient } from './frontend/packages/openmates-cli/dist/cli-internal-client.js';
		const client = new OpenMatesClient({ apiUrl: process.env.OPENMATES_API_URL });
		if (!client.hasSession()) throw new Error('Fresh owner session is missing');
		${body}`;
	return JSON.parse(mustRun('node', ['--input-type=module', '-e', program], { env: { OPENMATES_API_URL: apiUrl, ...env } }, label).trim());
}

function approveDevice(apiUrl: string, accessType: string, deviceId: string): void {
	const result = ownerProgram(apiUrl, `
		const keys = await client.listApiKeys();
		const fixture = (keys.api_keys || []).filter(key => key.name === 'Disposable CI fixture');
		if (fixture.length !== 1) throw new Error('Fresh fixture API key is not unique');
		const current = await client.settingsGet('api-key-devices');
		const matches = (current.devices || []).filter(device => device.api_key_id === fixture[0].id &&
			device.access_type === process.env.OPENMATES_DEVICE_ACCESS && device.machine_identifier === process.env.OPENMATES_DEVICE_IDENTITY);
		if (matches.length !== 1) throw new Error('Fixture device registration is not unique');
		if (!matches[0].approved_at) await client.settingsPost('api-key-devices/' + matches[0].id + '/approve', {});
		console.log(JSON.stringify({ approved: true }));`,
		{ OPENMATES_DEVICE_ACCESS: accessType, OPENMATES_DEVICE_IDENTITY: deviceId }, `${accessType} device approval`);
	expect(result.approved).toBe(true);
}

/** One request through a worker; registers the device on first use. */
function workerProbe(argv: string[], apiUrl: string, key: string, deviceId: string, label: string): any {
	const input = `${JSON.stringify({ api_url: apiUrl, api_key: key, device_id: deviceId })}\n${JSON.stringify({ op: 'drafts.list', args: {}, iterations: 1 })}\n`;
	const lines = mustRun(argv[0], argv.slice(1), { input }, label).trim().split('\n');
	expect(JSON.parse(lines[0])).toEqual({ ready: true });
	return JSON.parse(lines[1]);
}

test.describe('Cross-SDK speed check', () => {
	test.setTimeout(55 * 60_000);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;

	// contract-test: tooling
	test('Rust, npm/TypeScript and Python SDKs have no gross speed regression on real API-key operations', async ({}, testInfo: any) => { // eslint-disable-line no-empty-pattern -- Playwright requires a destructured first argument
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		expect(fs.existsSync(path.join(ROOT, 'frontend/packages/openmates-cli/dist/sdk-entry.js')), 'npm SDK dist is built').toBe(true);

		const targetDir = path.join(ROOT, 'target');
		await test.step('build the Rust worker and install the Python SDK', async () => {
			mustRun('rustup', ['toolchain', 'install', TOOLCHAIN, '--profile', 'minimal'], { timeout: 300_000 }, 'rustup');
			mustRun('cargo', [`+${TOOLCHAIN}`, 'build', '--release', '--locked', '-p', 'openmates-sdk', '--example', 'sdk-speed-worker',
				'--target-dir', targetDir], { env: { CARGO_INCREMENTAL: '0', CARGO_TERM_COLOR: 'never' }, timeout: 2_400_000 }, 'cargo build');
			mustRun('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
				path.join(ROOT, 'packages/openmates-python')], { timeout: 300_000 }, 'pip install');
		});
		const rustWorker = path.join(targetDir, 'release/examples/sdk-speed-worker');
		const workers: Record<string, string[]> = {
			rust: [rustWorker],
			npm: ['node', path.join(ROOT, 'tests/sdk-conformance/runners/sdk-speed-worker.mjs')],
			python: ['python3', path.join(ROOT, 'tests/sdk-conformance/runners/sdk-speed-worker.py')]
		};

		await test.step('register and approve one device per SDK', async () => {
			const probes: Record<string, unknown> = {};
			for (const [arm, argv] of Object.entries(workers)) {
				const deviceId = `${DEVICE_PREFIX}-${arm}`;
				let answer = workerProbe(argv, apiUrl, key!, deviceId, `${arm} registration`);
				if (!answer.ok && answer.error === 'forbidden') {
					approveDevice(apiUrl, ACCESS[arm], deviceId);
					answer = workerProbe(argv, apiUrl, key!, deviceId, `${arm} approved probe`);
				}
				probes[arm] = answer;
			}
			// Probe every SDK before asserting so one run reports each arm's state.
			for (const [arm, answer] of Object.entries(probes)) {
				expect(answer, `${arm} drafts probe after approval: ${JSON.stringify(probes)}`).toMatchObject({ ok: true });
			}
		});

		let draftChatId = '';
		await test.step('seed encrypted drafts through the owner session', async () => {
			const seeded = ownerProgram(apiUrl, `
				const { randomUUID } = await import('node:crypto');
				const ids = [];
				for (let i = 0; i < 8; i++) {
					const markdown = 'SDK speed draft ' + i + ': ' + 'Lorem ipsum dolor sit amet. '.repeat(64);
					const saved = await client.saveDraft({ chatId: randomUUID(), markdown, preview: markdown.slice(0, 120) });
					ids.push(saved.chatId);
				}
				console.log(JSON.stringify({ ids }));`, {}, 'draft seeding');
			expect(seeded.ids).toHaveLength(8);
			draftChatId = seeded.ids[0];
		});

		const report = testInfo.outputPath('sdk-speed-report.json');
		const entries = testInfo.outputPath('sdk-speed-perf-entries.json');
		const bench = run('python3', ['tests/sdk-conformance/benchmark_sdk_speed.py', '--api-url', apiUrl, '--rust-worker', rustWorker,
			'--device-prefix', DEVICE_PREFIX, '--draft-chat-id', draftChatId, '--pairs', '12', '--iterations', '2',
			'--output', report, '--perf-entries', entries, '--source-commit', process.env.BUILD_COMMIT_SHA || ''],
			{ env: { OPENMATES_API_KEY: key! }, timeout: 40 * 60_000 }, 'benchmark');
		console.log(bench.stdout);
		if (bench.stderr) console.log(bench.stderr.slice(-4000));
		expect(fs.existsSync(report), 'benchmark wrote its report').toBe(true);
		await testInfo.attach('sdk-speed-report', { path: report, contentType: 'application/json' });
		await testInfo.attach('sdk-speed-perf-entries', { path: entries, contentType: 'application/json' });
		// Also keep the report in the uploaded test-results tree for record_perf_measurement.py.
		fs.mkdirSync(path.join(ROOT, 'test-results/sdk-speed'), { recursive: true });
		fs.copyFileSync(report, path.join(ROOT, 'test-results/sdk-speed/sdk-speed-report.json'));
		fs.copyFileSync(entries, path.join(ROOT, 'test-results/sdk-speed/sdk-speed-perf-entries.json'));

		const parsed = JSON.parse(fs.readFileSync(report, 'utf8'));
		for (const row of parsed.operations) {
			expect.soft(row.status, `${row.op} measured in every SDK: ${JSON.stringify(row.failures ?? [])}`).toBe('measured');
			expect.soft(row.digest_equal, `${row.op} returned the same digest in every SDK: ${JSON.stringify(row.digests)}`).toBe(true);
			if (row.status !== 'measured') continue;
			for (const [metric, c] of Object.entries(row.comparisons.rust) as [string, any][]) {
				expect(c.gross_regression, `${row.op} ${metric} Rust/TS ${c.ratio} ${JSON.stringify(c.ci95)} delta ${c.median_delta_ms} ms`).toBe(false);
			}
			expect(row.rust_leak_suspected, `${row.op} Rust RSS growth ${row.rss_growth_kib.rust} KiB`).toBe(false);
		}
		expect(parsed.errors, 'benchmark errors').toEqual([]);
		expect(parsed.operations.length).toBeGreaterThanOrEqual(4);
	});
});
