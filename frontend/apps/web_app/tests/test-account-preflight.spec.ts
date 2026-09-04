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
// contract-test-file: tooling
// proof-video: not_required reason=account_health
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

function deriveApiUrl(baseUrl: string): string {
	if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL.replace(/\/$/, '');
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	} catch (error) {
		throw new Error(`PLAYWRIGHT_TEST_BASE_URL must be a valid URL when PLAYWRIGHT_TEST_API_URL is unset: ${String(error)}`);
	}
	throw new Error(`Cannot derive API URL from PLAYWRIGHT_TEST_BASE_URL=${baseUrl}. Set PLAYWRIGHT_TEST_API_URL explicitly.`);
}

test('configured account can complete password and OTP login', async ({ page }: { page: any }) => {
	test.setTimeout(120000);

	const { email, password, otpKey } = getTestAccount();
	const slot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || process.env.PLAYWRIGHT_WORKER_SLOT || '1';

	test.skip(!email || !password || !otpKey, `Missing credentials for test account slot ${slot}.`);

	const log = (message: string, metadata?: Record<string, unknown>) => {
		const suffix = metadata ? ` | meta=${JSON.stringify(metadata)}` : '';
		console.log(`[ACCOUNT_PREFLIGHT][slot ${slot}] ${message}${suffix}`);
	};

	log('Starting account preflight.', { email });
	await page.setViewportSize({ width: 1440, height: 900 });
	await loginToTestAccount(page, log, async () => undefined, { waitForEditor: false });
	log('Account preflight login succeeded.', { email });

	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) {
		throw new Error('Account preflight failed: browser session_id is missing after login.');
	}

	const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	const sessionCheck = await page.evaluate(async ({ apiUrl, sessionId }: { apiUrl: string; sessionId: string }) => {
		const response = await fetch(`${apiUrl}/v1/auth/session`, {
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json'
			},
			credentials: 'include',
			body: JSON.stringify({ session_id: sessionId })
		});
		const body = await response.json().catch(() => null);
		return { ok: response.ok, status: response.status, body };
	}, { apiUrl, sessionId });
	expect(sessionCheck.ok, 'Session API should accept the logged-in preflight account').toBe(true);
	const sessionPayload = sessionCheck.body;
	expect(sessionPayload?.success, `Session API should validate the logged-in preflight account; status=${sessionCheck.status}`).toBe(true);
	const accountId = sessionPayload?.user?.account_id;
	expect(
		accountId,
		'Persistent E2E account is missing users.account_id; billing invoice/payment confirmation tasks require it.'
	).toMatch(/^[A-Z0-9]{7}$/);
	log('Account preflight billing identity is present.', { accountId });

	await expect(page.getByTestId('header-github-link')).toBeVisible({ timeout: 15000 });
	log('Authenticated wide header is visible.', { email });

	await page.getByTestId('profile-container').click();
	await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('header-github-link')).toBeVisible({ timeout: 10000 });
	log('Authenticated wide header stays visible while settings are open.', { email });
});
