/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native Rust CLI `openmates apps code run` against the isolated CI stack.
 *
 * Real stack, no mocks: the native binary is paired with the CI test account, then
 *  (a) a fresh account without an E2B decision gets the consent refusal (exit 2, no TTY) and nothing runs;
 *  (b) out-of-scope flags (--url) are refused with a typed error and a non-zero exit;
 *  (c) --allow-e2b-upload passes the consent gate: no e2b_consent refusal (which would exit 2 at once),
 *      the server records `allowed`, and the run is accepted and queued. The isolated CI stack has no
 *      E2B key and no app-code worker, so the run never reaches a final status there; the CLI keeps
 *      polling until the bounded test timeout kills it. Real execution on E2B (program output,
 *      --dir/--entry projects) is proven on the dev host by scripts/cli_code_run_real_test.py;
 *  (d) a --dir that is not a directory is refused locally before any upload.
 */
export {};
import type { TestInfo } from '@playwright/test';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { rustEnv, runRust } = require('./helpers/rust-cli-terminal');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native: apps code run', () => {
	// The E2B decision is account state that a retry cannot reset, so a retry would fail the fresh-account precondition.
	test.describe.configure({ retries: 0 });
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: direct surface=cli assertions=code-run.e2b.upload-consent,code-run.request.validated,cli.runtime.native-rust
	test('refuses without consent, refuses unsafe flags, accepts the run once allowed', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'code-run');
		const api = process.env.PLAYWRIGHT_TEST_API_URL || diff.apiUrl;
		const env = rustEnv(diff.nativeHome, diff.apiUrl, process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const run = (args: string[], timeoutMs = 240_000) => runRust(diff.binary, env, args, timeoutMs);
		const decision = async (): Promise<string | null> => {
			const response = await page.request.get(`${api}/v1/settings/e2b-upload-consent`);
			expect(response.ok()).toBe(true);
			return (await response.json()).decision ?? null;
		};
		const work = fs.mkdtempSync(path.join(os.tmpdir(), 'cli-code-run-'));
		try {
			expect(await decision(), 'a fresh account has no decision').toBeNull();

			// (a) No consent and no TTY: typed refusal, exit 2, nothing uploaded or started.
			const refused = await run(['apps', 'code', 'run', '--language', 'python', '--code', 'print("hello from cli")']);
			expect(refused.code, refused.stderr).toBe(2);
			expect(refused.stderr).toContain('needs your permission before it sends your code and files to E2B');
			expect(refused.stderr).toContain('--allow-e2b-upload');
			expect(refused.stderr).toContain('Nothing was uploaded.');
			expect(refused.stdout).not.toContain('hello from cli');
			expect(await decision(), 'a refusal must not record a decision').toBeNull();

			// (b) Out-of-scope flag: typed error, non-zero exit, no run.
			const unsafe = await run(['apps', 'code', 'run', '--url', 'https://example.org/app.py', '--json']);
			expect(unsafe.code, unsafe.stderr + unsafe.stdout).not.toBe(0);
			const unsafeText = `${unsafe.stdout}${unsafe.stderr}`;
			expect(unsafeText).toContain('native_command_unsupported');
			expect(unsafeText).toContain('--url');

			// (c) --allow-e2b-upload passes the consent gate. A consent refusal exits 2 immediately, so a process
			// still running at the bounded timeout (killed: code null) means the server accepted and queued the run.
			const allowed = await run(['apps', 'code', 'run', '--language', 'python', '--code', 'print("hello from cli")', '--allow-e2b-upload'], 40_000);
			expect(allowed.stderr).not.toContain('e2b_consent');
			expect(allowed.stderr).not.toContain('needs your permission');
			expect(allowed.code, `CI has no E2B worker, so the queued run must still be polling: ${allowed.stderr}\n${allowed.stdout}`).toBeNull();
			expect(await decision()).toBe('allowed');

			// (d) Validation-only refusal: a --dir that is not a directory fails locally, nothing is sent.
			const missing = await run(['apps', 'code', 'run', '--dir', path.join(work, 'missing-project'), '--entry', 'main.py']);
			expect(missing.code, `${missing.stderr}\n${missing.stdout}`).not.toBe(0);
			expect(`${missing.stdout}${missing.stderr}`).toContain('is not a directory');
		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
