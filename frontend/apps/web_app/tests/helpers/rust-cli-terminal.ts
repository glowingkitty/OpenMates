/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native Rust CLI helpers for isolated-CI E2E specs.
 *
 * - `buildRustCli` compiles the exact checked-out `openmates` binary (release,
 *   locked) unless `OPENMATES_RUST_CLI_BIN` names an already built one.
 * - `runRust` runs one non-interactive command in a fresh process.
 * - `recordRust` runs one command in a real graphical PTY through
 *   scripts/cli_video_capture.py (Xvfb + Zutty + FFmpeg). Callers either type
 *   dynamic input (`typeText`/`key`) or pass a bounded input plan for the TUI.
 */
export {};
import type { TestInfo } from '@playwright/test';
const { execFileSync, spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../../..');
const TOOLCHAIN = '1.98.1';
let recorderReady = false;
let displayCounter = 0;

type RunResult = { code: number | null; stdout: string; stderr: string };
type TerminalStep = Record<string, unknown> & { name: string };
type CaptureManifest = { input_checkpoints?: Array<{ name: string; at_ms: number; transcript_offset: number }>; [key: string]: unknown };

function buildRustCli(testInfo: TestInfo): string {
	const supplied = process.env.OPENMATES_RUST_CLI_BIN;
	if (supplied) {
		if (!fs.existsSync(supplied)) throw new Error(`OPENMATES_RUST_CLI_BIN does not exist: ${supplied}`);
		return supplied;
	}
	const targetDir = path.join(ROOT, 'target');
	const started = Date.now();
	const run = (command: string, args: string[], timeout: number) => {
		const result = spawnSync(command, args, {
			cwd: ROOT,
			env: { ...process.env, CARGO_INCREMENTAL: '0', CARGO_TERM_COLOR: 'never' },
			encoding: 'utf8',
			timeout,
			maxBuffer: 64 * 1024 * 1024
		});
		if (result.status !== 0) {
			// Lead with compiler errors; warnings can fill the tail.
			const stderr = String(result.stderr);
			const errors = stderr.split('\n\n').filter((block) => /^error(\[|:)/m.test(block)).join('\n\n');
			throw new Error(`${command} ${args.join(' ')} failed (${result.status ?? result.signal}):\n${(errors || stderr).slice(-6000)}`);
		}
	};
	run('rustup', ['toolchain', 'install', TOOLCHAIN, '--profile', 'minimal'], 300_000);
	run('cargo', [`+${TOOLCHAIN}`, 'build', '--release', '--locked', '-p', 'openmates', '--bin', 'openmates', '--target-dir', targetDir], 2_400_000);
	const binary = path.join(targetDir, 'release', 'openmates');
	testInfo.annotations.push({ type: 'rust-cli-build', description: `cargo release build ${Math.round((Date.now() - started) / 1000)}s` });
	return binary;
}

/** Isolated native state: own HOME, state dir and an unreachable D-Bus so the
 * credential store deterministically uses its owner-only file fallback. */
function rustEnv(home: string, apiUrl: string, appUrl: string): Record<string, string | undefined> {
	return {
		...process.env,
		HOME: home,
		OPENMATES_STATE_DIR: path.join(home, '.openmates-rust'),
		OPENMATES_API_URL: apiUrl,
		OPENMATES_APP_URL: appUrl,
		OPENMATES_API_KEY: undefined,
		OPENMATES_PROFILE: undefined,
		DBUS_SESSION_BUS_ADDRESS: 'unix:path=/nonexistent/openmates-ci-no-bus',
		NO_COLOR: '1'
	};
}

function runRust(binary: string, env: Record<string, string | undefined>, args: string[], timeoutMs = 60_000): Promise<RunResult> {
	return new Promise((resolve, reject) => {
		const child = spawn(binary, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
		let stdout = '';
		let stderr = '';
		child.stdout.on('data', (chunk: Buffer) => (stdout += chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => (stderr += chunk.toString()));
		const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs);
		child.once('error', reject);
		child.once('close', (code: number | null) => {
			clearTimeout(timer);
			resolve({ code, stdout, stderr });
		});
	});
}

function ensureRecorder(): void {
	if (recorderReady) return;
	const missing = ['zutty', 'xdotool', 'Xvfb', 'ffmpeg', 'script'].some((name) => !fs.existsSync(`/usr/bin/${name}`));
	if (missing) {
		execFileSync('sudo', ['apt-get', 'install', '-y', 'zutty', 'fonts-dejavu-core', 'x11-xserver-utils', 'xdotool', 'ffmpeg', 'xvfb'], {
			cwd: ROOT,
			timeout: 180_000,
			stdio: 'pipe'
		});
	}
	recorderReady = true;
}

const plain = (text: string) =>
	// eslint-disable-next-line no-control-regex -- strip real terminal control sequences from the captured transcript.
	text.replace(/\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))/g, '').replace(/\r/g, '');

/**
 * Record `binary args` in a real terminal. Without `steps`, input comes from
 * `typeText`/`key`; with `steps`, cli_video_capture drives the bounded plan.
 */
function recordRust(
	binary: string,
	args: string[],
	env: Record<string, string | undefined>,
	testInfo: TestInfo,
	name: string,
	options: { steps?: TerminalStep[]; timeoutSeconds?: number } = {}
) {
	ensureRecorder();
	const outputDir = testInfo.outputPath(`rust-terminal-${name}`);
	fs.mkdirSync(outputDir, { recursive: true });
	displayCounter += 1;
	const displayNumber = 150 + Number(process.env.PLAYWRIGHT_WORKER_SLOT || '0') * 20 + displayCounter;
	const display = `:${displayNumber}`;
	const terminalEnv = { ...env, DISPLAY: display, TERM: 'xterm-256color', LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' };
	const captureArgs = [
		path.join(ROOT, 'scripts/cli_video_capture.py'),
		'--output-dir', outputDir,
		'--target-environment', 'isolated-ci',
		'--classification', `cli_rust_${name.replace(/-/g, '_')}`,
		'--display-number', String(displayNumber),
		'--timeout-seconds', String(options.timeoutSeconds ?? 120),
		'--no-response-media'
	];
	if (options.steps) {
		const plan = path.join(outputDir, 'input-plan.json');
		fs.writeFileSync(plan, JSON.stringify({ steps: options.steps }, null, 2));
		captureArgs.push('--input-plan', plan);
	}
	const child = spawn('python3', [...captureArgs, '--', binary, ...args], {
		cwd: ROOT,
		env: terminalEnv,
		stdio: ['ignore', 'pipe', 'pipe']
	});
	let closed = false;
	let captureStdout = '';
	let captureStderr = '';
	child.stdout.on('data', (chunk: Buffer) => (captureStdout += chunk.toString()));
	child.stderr.on('data', (chunk: Buffer) => (captureStderr += chunk.toString()));
	const exit = new Promise<number | null>((resolve, reject) => {
		child.once('error', reject);
		child.once('close', (code: number | null) => {
			closed = true;
			resolve(code);
		});
	});
	const transcriptPath = path.join(outputDir, 'transcript.txt');
	const transcript = () => (fs.existsSync(transcriptPath) ? fs.readFileSync(transcriptPath, 'utf8') : '');
	const xdotool = (xArgs: string[], input?: string) =>
		execFileSync('xdotool', xArgs, { env: terminalEnv, input, encoding: 'utf8', timeout: 8_000 });
	const focus = () => {
		const id = xdotool(['search', '--onlyvisible', '--name', '^OpenMates CLI$']).trim().split('\n').at(-1);
		xdotool(['windowfocus', '--sync', id]);
	};
	let attached = false;
	const handle = {
		outputDir,
		transcript,
		plainTranscript: () => plain(transcript()),
		async waitForOutput(pattern: RegExp, timeoutMs = 30_000): Promise<RegExpMatchArray> {
			const deadline = Date.now() + timeoutMs;
			while (Date.now() < deadline) {
				const match = plain(transcript()).match(pattern);
				if (match) return match;
				if (closed) break;
				await new Promise((resolve) => setTimeout(resolve, 100));
			}
			throw new Error(`Terminal ${name} did not reach ${pattern}:\n${plain(transcript()).slice(-3000)}\n${captureStdout}${captureStderr}`);
		},
		typeText(text: string): void {
			focus();
			xdotool(['type', '--clearmodifiers', '--delay', '15', '--file', '-'], text);
		},
		key(keyName: string): void {
			focus();
			xdotool(['key', '--clearmodifiers', keyName]);
		},
		/** Command exit status as recorded by util-linux script inside the PTY. */
		async waitForExit(timeoutMs = 60_000): Promise<{ code: number; output: string; manifest: CaptureManifest }> {
			let timer: ReturnType<typeof setTimeout> | undefined;
			try {
				await Promise.race([
					exit,
					new Promise<never>((_, reject) => {
						timer = setTimeout(() => reject(new Error(`Terminal ${name} did not exit:\n${plain(transcript()).slice(-3000)}`)), timeoutMs);
					})
				]);
			} finally {
				clearTimeout(timer);
			}
			const manifestPath = path.join(outputDir, 'manifest.json');
			if (!fs.existsSync(manifestPath)) throw new Error(`Terminal ${name} produced no capture manifest: ${captureStdout}${captureStderr}`);
			const manifest: CaptureManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
			if (manifest.capture_kind !== 'real_terminal_screen' || manifest.reconstructed !== false) {
				throw new Error(`Terminal ${name} is not a real terminal capture`);
			}
			if (manifest.input_error) throw new Error(`Terminal ${name} input plan failed: ${manifest.input_error}\n${plain(transcript()).slice(-3000)}`);
			const status = transcript().match(/Script done on .*\[COMMAND_EXIT_CODE="(\d+)"\]/);
			if (!status) throw new Error(`Terminal ${name} has no recorded command status: ${captureStdout}${captureStderr}`);
			return { code: Number(status[1]), output: plain(transcript()), manifest };
		},
		async dispose(): Promise<void> {
			if (!closed) child.kill('SIGTERM');
			await exit.catch(() => undefined);
			if (attached) return;
			attached = true;
			for (const [label, file, contentType] of [
				['openmates-cli-real-terminal-video', 'raw-terminal.mp4', 'video/mp4'],
				['openmates-cli-real-terminal-manifest', 'manifest.json', 'application/json'],
				['openmates-cli-real-terminal-transcript', 'transcript.txt', 'text/plain'],
				['openmates-cli-real-terminal-events', 'events.jsonl', 'application/jsonl']
			]) {
				const artifact = path.join(outputDir, file);
				if (fs.existsSync(artifact)) await testInfo.attach(`${label}-${name}`, { path: artifact, contentType });
			}
		}
	};
	return handle;
}

function createRustHome(prefix: string): string {
	return fs.mkdtempSync(path.join(os.tmpdir(), `openmates-rust-${prefix}-`));
}

module.exports = { buildRustCli, createRustHome, recordRust, runRust, rustEnv, plainTerminalText: plain };
