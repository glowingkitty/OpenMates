/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Self-hosted install smoke test.
 *
 * Runs against a GitHub Actions-provisioned local self-hosted stack. This test
 * intentionally avoids chat, LLM calls, provider APIs, and app skills so the
 * minimum installer can be verified without secrets or paid external services.
 */

const { test, expect } = require('@playwright/test');

const SELFHOST_API_URL = process.env.SELFHOST_API_URL || 'http://localhost:8000';

test('self-hosted web app loads and reaches backend status', async ({ page, request }) => {
	const pageResponse = await page.goto('/');
	expect(pageResponse?.ok(), 'web app root should respond successfully').toBe(true);

	await page.waitForLoadState('networkidle');
	const bodyText = await page.evaluate(() => document.body.textContent || '');
	expect(bodyText.length, 'web app should render visible content').toBeGreaterThan(20);

	const apiResponse = await request.get(`${SELFHOST_API_URL}/v1/settings/server-status`);
	expect(apiResponse.ok(), 'backend server status endpoint should respond').toBe(true);

	const status = await apiResponse.json();
	expect(status.is_self_hosted).toBe(true);
	expect(status.payment_enabled).toBe(false);
	expect(status.ai_models_configured).toBe(false);

	const sessionResponse = await request.post(`${SELFHOST_API_URL}/v1/auth/session`);
	expect(sessionResponse.ok(), 'unauthenticated session endpoint should respond').toBe(true);
	const session = await sessionResponse.json();
	expect(session.success).toBe(false);
	expect(session.require_invite_code).toBe(true);

	const browserStatus = await page.evaluate(async (apiUrl: string) => {
		const response = await fetch(`${apiUrl}/v1/settings/server-status`);
		return {
			ok: response.ok,
			status: response.status,
			json: await response.json()
		};
	}, SELFHOST_API_URL);

	expect(browserStatus.ok, `browser fetch failed with ${browserStatus.status}`).toBe(true);
	expect(browserStatus.json.is_self_hosted).toBe(true);
});
