/** Development registry and internal health probe regression coverage. */
import { test, expect } from './helpers/cookie-audit';
import { arch, platform } from 'node:os';
import { splitApiKeyCredential } from '../../../packages/openmates-cli/src/crypto';

// contract-test: direct surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise,operational-monitoring.billing.no-spend-readiness
test('development apps load in health worker and payment probe requires internal auth', async ({ request }: { request: any }) => {
	test.setTimeout(120_000);
	const apiUrl = process.env.OPENMATES_E2E_API_URL || process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000';
	await expect.poll(async () => {
		const response = await request.get(`${apiUrl}/v1/health`);
		expect(response.ok()).toBe(true);
		const health = await response.json();
		return [
			...['tasks', 'projects', 'plans'].map((id) => health.apps?.[id]?.api?.status),
			// The disposable core worker intentionally does not consume app_videos.
			health.apps?.videos?.api?.status,
			health.apps?.videos?.worker?.status,
			health.apps?.videos?.status,
		];
	}, { timeout: 90_000, intervals: [1000, 2000, 5000] }).toEqual([
		'healthy', 'healthy', 'healthy', 'healthy', 'unhealthy', 'degraded',
	]);
	const probe = await request.get(`${apiUrl}/internal/health/payments`);
	expect(probe.status()).toBe(401);
});

// contract-test: direct surface=rest_api assertions=app-skills.surface.semantic-parity,operational-monitoring.alerts.actionable-low-noise
test('catalog retains unpriced providers and search skills load their request schemas', async ({ request }: { request: any }) => {
	test.setTimeout(60_000);
	const apiUrl = process.env.OPENMATES_E2E_API_URL || process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000';
	const apiKey = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
	expect(apiKey, 'Disposable test-account API key is required').toBeTruthy();
	// CI provisions this real CLI device and approves it through its owner's
	// session. Send only the bearer part of the setup credential, as the SDK does.
	const headers = {
		Authorization: `Bearer ${splitApiKeyCredential(apiKey || '').bearer}`,
		'X-OpenMates-SDK': 'cli',
		'X-OpenMates-Device-Identity': `cli:${platform()}:${arch()}`
	};

	const unauthorized = await request.get(`${apiUrl}/v1/apps`);
	expect(unauthorized.status()).toBe(401);
	const catalog = await request.get(`${apiUrl}/v1/apps?include_unavailable=true`, { headers });
	expect(catalog.status(), 'App catalog must accept the approved fixture credential').toBe(200);
	const { apps } = await catalog.json();
	const providers = apps.flatMap((app: any) => app.skills.flatMap((skill: any) => skill.providers));
	for (const id of ['openmates', 'google']) {
		const matching = providers.filter((provider: any) => provider.provider === id);
		expect(matching.length, `${id} metadata must remain available without provider-level pricing`).toBeGreaterThan(0);
		for (const provider of matching) {
			expect(provider.name).toBeTruthy();
			expect(provider.pricing).toEqual({});
		}
	}

	// Missing query is rejected by the real skill's imported Pydantic schema,
	// before execution or paid provider calls. An unresolved class gives 404.
	for (const app of ['news', 'videos']) {
		const invalid = await request.post(`${apiUrl}/v1/apps/${app}/skills/search`, {
			headers, data: { requests: [{}] }
		});
		expect(invalid.status(), `${app}.search must have a loaded request schema`).toBe(422);
	}
});
