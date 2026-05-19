/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Verifies that one configured persistent E2E account can complete login.
 *
 * The Python test orchestrator dispatches this spec once per account slot before
 * the nightly Playwright suite. It catches stale password/OTP GitHub secrets
 * before unrelated feature specs fail during setup.
 *
 * Architecture: docs/architecture/e2e-testing.md
 */
export {};

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

test('configured account can complete password and OTP login', async ({ page }: { page: any }) => {
	const { email, password, otpKey } = getTestAccount();
	const slot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || process.env.PLAYWRIGHT_WORKER_SLOT || '1';

	test.skip(!email || !password || !otpKey, `Missing credentials for test account slot ${slot}.`);

	const log = (message: string, metadata?: Record<string, unknown>) => {
		const suffix = metadata ? ` | meta=${JSON.stringify(metadata)}` : '';
		console.log(`[ACCOUNT_PREFLIGHT][slot ${slot}] ${message}${suffix}`);
	};

	log('Starting account preflight.', { email });
	await loginToTestAccount(page, log, async () => undefined, { waitForEditor: false });
	log('Account preflight login succeeded.', { email });
});
