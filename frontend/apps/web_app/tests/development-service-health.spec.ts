/** Development registry and internal health probe regression coverage. */
import { test, expect } from './helpers/cookie-audit';

// contract-test: direct surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise,operational-monitoring.billing.no-spend-readiness
test('development apps load in health worker and payment probe requires internal auth', async ({ request }: { request: any }) => {
	test.setTimeout(120_000);
	const apiUrl = process.env.OPENMATES_E2E_API_URL || process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000';
	await expect.poll(async () => {
		const response = await request.get(`${apiUrl}/v1/health`);
		expect(response.ok()).toBe(true);
		const health = await response.json();
		return ['tasks', 'projects', 'plans'].map((id) => health.apps?.[id]?.api?.status);
	}, { timeout: 90_000, intervals: [1000, 2000, 5000] }).toEqual(['healthy', 'healthy', 'healthy']);
	const probe = await request.get(`${apiUrl}/internal/health/payments`);
	expect(probe.status()).toBe(401);
});
