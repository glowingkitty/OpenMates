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

const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const REPOSITORY_ROOT = path.resolve(__dirname, '../../../../..');
let cliRecordingCreated = false;

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

function extractCliProofFrame(
	videoPath: string,
	run = spawnSync
): Buffer {
	const result = run('ffmpeg', [
		'-v', 'error',
		'-sseof', '-0.1',
		'-i', videoPath,
		'-frames:v', '1',
		'-f', 'image2pipe',
		'-vcodec', 'png',
		'pipe:1'
	], {encoding: null, maxBuffer: 16 * 1024 * 1024});
	if (result.error || result.status !== 0 || !Buffer.isBuffer(result.stdout) || result.stdout.length === 0) {
		const detail = result.error?.message || result.stderr?.toString() || 'empty frame output';
		throw new Error(`CLI proof frame extraction failed: ${String(detail).slice(-1000)}`);
	}
	return result.stdout;
}

/**
 * Spawn the CLI with API key auth and return stdout/stderr/exit code.
 * Automatically prepends --api-key if OPENMATES_TEST_ACCOUNT_API_KEY is set.
 */
async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 30_000,
	options: { useApiKey?: boolean; record?: boolean; env?: Record<string, string | undefined> } = {}
): Promise<{ code: number | null; stdout: string; stderr: string; durationMs: number; recording?: Record<string, string> }> {
	const apiKey = options.useApiKey === false ? undefined : process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	const allArgs = apiKey ? ['--api-key', apiKey, ...args] : args;
	const shouldRecord = options.record !== false
		&& (process.env.OPENMATES_CLI_RECORD_E2E === '1' || options.env?.OPENMATES_CLI_RECORD_E2E === '1')
		&& !cliRecordingCreated;
	if (shouldRecord) {
		cliRecordingCreated = true;
		const startedAt = performance.now();
		const specSlug = String(options.env?.OPENMATES_E2E_SPEC || process.env.OPENMATES_E2E_SPEC || 'openmates-cli-e2e')
			.replace(/\.spec\.ts$/, '')
			.replace(/[^A-Za-z0-9._-]+/g, '-');
		const outputDir = path.resolve(process.cwd(), 'test-results', 'cli-recordings', specSlug);
		fs.rmSync(outputDir, {recursive: true, force: true});
		const recorderArgs = [
			path.join(REPOSITORY_ROOT, 'scripts/cli_video_capture.py'),
			'--output-dir', outputDir,
			'--target-environment', apiUrl,
			'--display-number', String(100 + Number(process.env.PLAYWRIGHT_WORKER_SLOT || '1')),
			'--timeout-seconds', String(Math.max(30, Math.ceil(timeoutMs / 1000))),
			'--', 'node', CLI_DIST, ...args
		];
		return new Promise((resolve) => {
			const child = spawn('python3', recorderArgs, {
				cwd: REPOSITORY_ROOT,
				env: {
					...process.env,
					...options.env,
					...(apiKey ? {OPENMATES_API_KEY: apiKey} : {}),
					OPENMATES_API_URL: apiUrl,
					OPENMATES_CLI_HTTP_TIMEOUT_MS: process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS ?? String(timeoutMs),
					NODE_PATH: path.join(cliDir, 'node_modules'),
					TERM: 'xterm-256color'
				},
				stdio: ['ignore', 'pipe', 'pipe']
			});
			const out: string[] = [];
			const err: string[] = [];
			child.stdout.on('data', (chunk: Buffer) => out.push(chunk.toString()));
			child.stderr.on('data', (chunk: Buffer) => err.push(chunk.toString()));
			child.on('close', (code: number | null) => {
				try {
					const line = out.join('').trim().split('\n').at(-1) || '{}';
					const payload = JSON.parse(line);
					const manifest = payload.manifest || {};
					const stdout = manifest.command_output_path && fs.existsSync(manifest.command_output_path)
						? fs.readFileSync(manifest.command_output_path, 'utf8')
						: out.join('');
					resolve({
						code: manifest.exit_status ?? code,
						stdout,
						stderr: err.join(''),
						durationMs: performance.now() - startedAt,
						recording: {
							outputDir,
							videoPath: String(manifest.video_path || path.join(outputDir, 'raw-terminal.mp4')),
							manifestPath: String(manifest.manifest_path || path.join(outputDir, 'manifest.json')),
							transcriptPath: String(manifest.transcript_path || path.join(outputDir, 'transcript.txt')),
							eventsPath: String(manifest.events_path || path.join(outputDir, 'events.jsonl'))
						}
					});
				} catch (error: any) {
					resolve({code, stdout: out.join(''), stderr: `${err.join('')}\n${error.message}`, durationMs: performance.now() - startedAt});
				}
			});
		});
	}

	return new Promise((resolve) => {
		const startedAt = performance.now();
		// cli-e2e-recording: shared-recorder-fallback
		const child = spawn('node', [CLI_DIST, ...allArgs], {
			env: {
				...process.env,
				...options.env,
				OPENMATES_API_URL: apiUrl,
				OPENMATES_CLI_HTTP_TIMEOUT_MS: process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS ?? String(timeoutMs),
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
			resolve({ code: null, stdout: out.join(''), stderr: err.join(''), durationMs: performance.now() - startedAt });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: out.join(''), stderr: err.join(''), durationMs: performance.now() - startedAt });
		});
	});
}

async function runCliProof(
	apiUrl: string,
	args: string[],
	testInfo: any,
	definition: any,
	timeoutMs = 30_000,
	options: { useApiKey?: boolean; env?: Record<string, string | undefined> } = {}
): Promise<{ result: { code: number | null; stdout: string; stderr: string; durationMs: number; recording?: Record<string, string> }; proof: any; recording: Record<string, string> }> {
	const { createVideoProofRuntime } = require('./video-proof.ts');
	const specName = path.basename(testInfo.file || process.env.OPENMATES_E2E_SPEC || 'openmates-cli-e2e.spec.ts');
	const proofState: {recording?: Record<string, string>} = {};
	const proof = createVideoProofRuntime(definition, {
		device: 'cli-terminal',
		attach: async (name: string, attachment: {body: Buffer; contentType: string}) => testInfo.attach(name, attachment),
		captureFrame: async () => {
			if (!proofState.recording) throw new Error('CLI proof checkpoint was captured before the terminal recording completed');
			return extractCliProofFrame(proofState.recording.videoPath);
		}
	});
	const result = await proof.action('run-openmates-cli', async () => runCli(apiUrl, args, timeoutMs, {
		...options,
		env: {
			...options.env,
			OPENMATES_CLI_RECORD_E2E: '1',
			OPENMATES_E2E_SPEC: specName
		}
	}));
	if (!result.recording) throw new Error('CLI proof run did not produce a real terminal recording');
	const recording = result.recording;
	proofState.recording = recording;
	await testInfo.attach('openmates-cli-real-terminal-video', {path: recording.videoPath, contentType: 'video/mp4'});
	await testInfo.attach('openmates-cli-real-terminal-manifest', {path: recording.manifestPath, contentType: 'application/json'});
	await testInfo.attach('openmates-cli-real-terminal-transcript', {path: recording.transcriptPath, contentType: 'text/plain'});
	if (fs.existsSync(recording.eventsPath)) {
		await testInfo.attach('openmates-cli-real-terminal-events', {path: recording.eventsPath, contentType: 'application/jsonl'});
	}
	return {result, proof, recording};
}

/**
 * Parse CLI JSON output and validate the success envelope.
 * Throws with helpful error if parsing or validation fails.
 */
function parseCliJson(result: { code: number | null; stdout: string; stderr: string }): any {
	let parsed: any;
	try {
		parsed = JSON.parse(result.stdout);
	} catch {
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
	extractCliProofFrame,
	runCli,
	runCliProof,
	parseCliJson,
	expectCliSuccess
};
