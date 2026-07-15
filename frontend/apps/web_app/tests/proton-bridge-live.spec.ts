/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Live Proton Mail Bridge smoke coverage.
 *
 * Purpose: prove GitHub Actions can install Proton Mail Bridge, log into the
 * dedicated Proton test account, and read local IMAP/SMTP credentials from
 * Bridge `info` output without exposing those credentials in logs.
 * Architecture: docs/specs/proton-bridge-cli-connector/spec.yml
 * Security: all provider passwords, 2FA codes, and Bridge-generated passwords
 * are redacted before any diagnostic output is emitted.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { generateTotp } = require('./signup-flow-helpers');
const { spawn, execFileSync } = require('node:child_process');

const PROTON_EMAIL = process.env.PROTON_BRIDGE_TEST_EMAIL;
const PROTON_PASSWORD = process.env.PROTON_BRIDGE_TEST_PASSWORD;
const PROTON_TOTP_KEY = process.env.PROTON_BRIDGE_TEST_TOTP_KEY;

const BRIDGE_COMMANDS = ['protonmail-bridge', 'proton-mail-bridge'];
const BRIDGE_ARGS = ['--cli'];
const BRIDGE_READY_RE = /No active accounts\. Please add account to continue\.|>{3,}|bridge>\s*$/im;
const BRIDGE_AUTH_FAILURE_RE = /invalid|incorrect|authentication failed|login failed|wrong password|bad credentials/i;
const SECRET_PROMPT_VALUE_RE = /((?:password|token|secret|2fa|totp|code)[^:\r\n]*:\s*)[^\r\n]*/gim;
const ANSI_ESCAPE_RE = new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, 'g');
const TERMINAL_CONTROL_RE = new RegExp(`[${String.fromCharCode(8)}${String.fromCharCode(13)}]`, 'g');

function findBridgeBinary(): string | null {
	for (const command of BRIDGE_COMMANDS) {
		try {
			const path = execFileSync('bash', ['-lc', `command -v ${command}`], {
				encoding: 'utf8',
				stdio: ['ignore', 'pipe', 'ignore']
			}).trim();
			if (path) return path;
		} catch {
			// Try the next known binary name.
		}
	}
	return null;
}

function redactBridgeOutput(output: string): string {
	let redacted = output.replace(SECRET_PROMPT_VALUE_RE, '$1<redacted>');
	for (const value of [PROTON_EMAIL, PROTON_PASSWORD, PROTON_TOTP_KEY]) {
		if (value) redacted = redacted.split(value).join('<redacted>');
	}
	return redacted;
}

function normalizeBridgeOutputForMatching(output: string): string {
	return output.replace(ANSI_ESCAPE_RE, '').replace(TERMINAL_CONTROL_RE, '');
}

function waitForOutput(
	getOutput: () => string,
	pattern: RegExp,
	label: string,
	timeoutMs = 30_000
): Promise<void> {
	const startedAt = Date.now();
	return new Promise((resolve, reject) => {
		const tick = () => {
			const output = getOutput();
			const normalizedOutput = normalizeBridgeOutputForMatching(output);
			if (pattern.test(normalizedOutput)) {
				resolve();
				return;
			}
			if (Date.now() - startedAt > timeoutMs) {
				reject(new Error(`Timed out waiting for ${label}. Output:\n${redactBridgeOutput(output).slice(-3000)}`));
				return;
			}
			setTimeout(tick, 250);
		};
		tick();
	});
}

function waitForEitherOutput(
	getOutput: () => string,
	patterns: Array<{ label: string; pattern: RegExp }>,
	timeoutMs = 30_000
): Promise<string> {
	const startedAt = Date.now();
	return new Promise((resolve, reject) => {
		const tick = () => {
			const output = getOutput();
			const normalizedOutput = normalizeBridgeOutputForMatching(output);
			for (const candidate of patterns) {
				if (candidate.pattern.test(normalizedOutput)) {
					resolve(candidate.label);
					return;
				}
			}
			if (Date.now() - startedAt > timeoutMs) {
				reject(new Error(`Timed out waiting for ${patterns.map((p) => p.label).join(' or ')}. Output:\n${redactBridgeOutput(output).slice(-3000)}`));
				return;
			}
			setTimeout(tick, 250);
		};
		tick();
	});
}

function extractInfoSection(output: string): string {
	const infoIndex = output.toLowerCase().lastIndexOf('info');
	return infoIndex >= 0 ? output.slice(infoIndex) : output;
}

function shellQuote(value: string): string {
	return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function spawnBridgeCli(bridgeBinary: string) {
	if (process.platform === 'linux') {
		return spawn('script', ['-qfec', `${shellQuote(bridgeBinary)} ${BRIDGE_ARGS.join(' ')}`, '/dev/null'], {
			env: {
				...process.env,
				TERM: 'dumb'
			},
			stdio: ['pipe', 'pipe', 'pipe']
		});
	}

	return spawn(bridgeBinary, BRIDGE_ARGS, {
		env: {
			...process.env,
			TERM: 'dumb'
		},
		stdio: ['pipe', 'pipe', 'pipe']
	});
}

test.describe('Proton Bridge live connector smoke', () => {
	test.describe.configure({ timeout: 180000 });

	test('logs into Bridge and exposes localhost IMAP/SMTP info without leaking secrets', async () => {
		test.skip(!PROTON_EMAIL || !PROTON_PASSWORD, 'PROTON_BRIDGE_TEST_EMAIL and PROTON_BRIDGE_TEST_PASSWORD are required for live Proton Bridge smoke coverage.');

		const bridgeBinary = findBridgeBinary();
		test.skip(!bridgeBinary, 'Proton Mail Bridge binary is not installed on this runner.');

		const child = spawnBridgeCli(bridgeBinary);

		let output = '';
		let outputCheckpoint = 0;
		const newOutput = () => output.slice(outputCheckpoint);
		const markOutputCheckpoint = () => {
			outputCheckpoint = output.length;
		};
		child.stdout.on('data', (data: Buffer) => {
			output += data.toString();
		});
		child.stderr.on('data', (data: Buffer) => {
			output += data.toString();
		});

		try {
			await waitForOutput(newOutput, BRIDGE_READY_RE, 'initial Bridge prompt');
			markOutputCheckpoint();
			child.stdin.write('add\n');

			await waitForOutput(newOutput, /username|email|login/i, 'Bridge username prompt');
			markOutputCheckpoint();
			child.stdin.write(`${PROTON_EMAIL}\n`);

			await waitForOutput(newOutput, /password/i, 'Bridge password prompt');
			markOutputCheckpoint();
			child.stdin.write(`${PROTON_PASSWORD}\n`);

			const postPasswordState = await waitForEitherOutput(
				newOutput,
				[
					{ label: 'auth-failed', pattern: BRIDGE_AUTH_FAILURE_RE },
					{ label: 'totp', pattern: /2fa|two[- ]?factor|totp|authenticator|verification code/i },
					{ label: 'logged-in', pattern: /logged in|signed in|account added|already.*logged|successfully added/i },
					{ label: 'prompt', pattern: BRIDGE_READY_RE }
				],
				45_000
			);
			markOutputCheckpoint();
			if (postPasswordState === 'auth-failed') throw new Error('Bridge rejected Proton account credentials.');

			if (postPasswordState === 'totp') {
				test.skip(!PROTON_TOTP_KEY, 'PROTON_BRIDGE_TEST_TOTP_KEY is required when the Proton account prompts for 2FA.');
				child.stdin.write(`${generateTotp(PROTON_TOTP_KEY)}\n`);
				const postTotpState = await waitForEitherOutput(
					newOutput,
					[
						{ label: 'auth-failed', pattern: BRIDGE_AUTH_FAILURE_RE },
						{ label: 'logged-in', pattern: /logged in|signed in|account added|already.*logged|successfully added/i },
						{ label: 'prompt', pattern: BRIDGE_READY_RE }
					],
					45_000
				);
				markOutputCheckpoint();
				if (postTotpState === 'auth-failed') throw new Error('Bridge rejected Proton account 2FA code.');
			}

			child.stdin.write('info\n');
			await waitForOutput(newOutput, /imap|smtp/i, 'Bridge info output', 30_000);

			const info = extractInfoSection(output);
			expect(info).toMatch(/imap/i);
			expect(info).toMatch(/smtp/i);
			expect(info).toMatch(/127\.0\.0\.1|localhost/i);
			expect(redactBridgeOutput(info)).not.toContain(PROTON_PASSWORD as string);
			if (PROTON_TOTP_KEY) expect(redactBridgeOutput(info)).not.toContain(PROTON_TOTP_KEY);
		} catch (error) {
			throw new Error(`${error instanceof Error ? error.message : String(error)}\nSanitized Bridge output:\n${redactBridgeOutput(output).slice(-3000)}`);
		} finally {
			child.stdin.write('exit\n');
			child.kill('SIGTERM');
		}
	});
});
