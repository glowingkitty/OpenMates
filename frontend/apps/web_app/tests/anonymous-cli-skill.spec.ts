/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Public anonymous app-skill REST boundary on the isolated API fixture. */
const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');

test.describe('Anonymous CLI skill boundary', () => {
	// contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
	test('requires an anonymous identity before a skill can run', async ({ request }: { request: any }) => {
		const response = await request.post(`${API_URL}/v1/anonymous/apps/web/skills/search`, {
			data: { requests: [{ query: 'OpenMates' }] }
		});
		expect(response.status()).toBe(422);
		expect((await response.json()).detail.code).toBe('anonymous_id_required');
	});

	// contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
	test('rejects private embed references before provider dispatch', async ({ request }: { request: any }) => {
		const response = await request.post(`${API_URL}/v1/anonymous/apps/web/skills/search`, {
			headers: { 'X-OpenMates-Anonymous-ID': 'e2e-guest-skill-privacy' },
			data: { requests: [{ query: 'OpenMates', embed_id: 'private-embed' }] }
		});
		expect(response.status()).toBe(403);
		expect((await response.json()).detail.code).toBe('signup_required');
	});

	// contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering,billing.anonymous.local-only-content
	test('requires authentication for file, background, and durable-write skills', async ({ request }: { request: any }) => {
		for (const [app, skill] of [
			['images', 'generate'], ['social_media', 'search'],
			['web', 'read'], ['videos', 'get_transcript']
		]) {
			const response = await request.post(`${API_URL}/v1/anonymous/apps/${app}/skills/${skill}`, {
				headers: { 'X-OpenMates-Anonymous-ID': 'e2e-guest-skill-file-gate' },
				data: { requests: [{ query: 'OpenMates', prompt: 'A blue circle' }] }
			});
			expect(response.status()).toBe(403);
			expect((await response.json()).detail.code).toBe('signup_required');
		}
	});
});
