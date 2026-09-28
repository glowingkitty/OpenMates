/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');

// contract-test: direct surface=rest_api assertions=billing.anonymous.daily-remaining-percent
test('public guest status returns a bounded daily percentage without credit counts', async ({ request }: { request: any }) => {
	const withoutIdentity = await request.get(`${API_URL}/v1/anonymous/free-usage/status`);
	expect(withoutIdentity.status()).toBe(200);
	expect((await withoutIdentity.json()).daily_remaining_percent).toBeNull();

	const withIdentity = await request.get(`${API_URL}/v1/anonymous/free-usage/status`, {
		params: { anonymous_id: `e2e-guest-status-${Date.now()}` }
	});
	expect(withIdentity.status()).toBe(200);
	const status = await withIdentity.json();
	expect(Number.isInteger(status.daily_remaining_percent)).toBe(true);
	expect(status.daily_remaining_percent).toBeGreaterThanOrEqual(0);
	expect(status.daily_remaining_percent).toBeLessThanOrEqual(100);
	expect(status).not.toHaveProperty('daily_remaining_credits');
	expect(status).not.toHaveProperty('per_identity_daily_cap_credits');
});
