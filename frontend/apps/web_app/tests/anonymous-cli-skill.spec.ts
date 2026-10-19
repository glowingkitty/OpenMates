/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Public anonymous app-skill REST boundary on the isolated API fixture. */
const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
const decisionInput = {
	state: { health: 10, enemyNearby: true },
	questions: { retreat: { type: 'noul', instructions: 'Should the player retreat?' } }
};

test.describe('Anonymous CLI skill boundary', () => {
	// contract-test: direct surface=rest_api assertions=ai-decide.request.bounded
	test('authenticated decision route stays private', async ({ request }: { request: any }) => {
		const account = await request.post(`${API_URL}/v1/apps/ai/skills/decide`, { data: decisionInput });
		expect(account.status()).toBe(401);
	});

	// contract-test: direct surface=rest_api assertions=ai-decide.request.bounded
	test('decision validation rejects model overrides, invalid questions and oversized input before inference', async ({ request }: { request: any }) => {
		const headers = { 'X-OpenMates-Anonymous-ID': 'e2e-decision-input-boundary' };
		for (const data of [
			{ ...decisionInput, model: 'caller-selected-model' },
			{ ...decisionInput, questions: {} },
			{ ...decisionInput, state: 'x'.repeat(17000) }
		]) {
			const response = await request.post(`${API_URL}/v1/anonymous/apps/ai/skills/decide`, { headers, data });
			expect(response.status()).toBe(422);
		}
	});

	// contract-test: direct surface=rest_api assertions=ai-decide.images.inline
	test('decision image validation rejects malformed, remote and oversized assets before inference', async ({ request }: { request: any }) => {
		const imageRef = '00000000-0000-4000-8000-000000000001';
		const imageInput = { ...decisionInput, state: { photo: imageRef } };
		const headers = { 'X-OpenMates-Anonymous-ID': 'e2e-decision-image-boundary' };
		for (const image of [
			{ type: 'image', format: 'png', data_base64: 'not base64!' },
			{ type: 'image', format: 'png', url: 'https://example.invalid/private-image.png' },
			{ type: 'image', format: 'png', data_base64: Buffer.alloc(1024 * 1024 + 1).toString('base64') }
		]) {
			const response = await request.post(`${API_URL}/v1/anonymous/apps/ai/skills/decide`, {
				headers, data: { ...imageInput, assets: { [imageRef]: image } }
			});
			expect(response.status()).toBe(422);
		}
		const oversizedBody = await request.post(`${API_URL}/v1/anonymous/apps/ai/skills/decide`, {
			headers, data: { ...imageInput, ignored: 'x'.repeat(6 * 1024 * 1024) }
		});
		expect(oversizedBody.status()).toBe(413);
	});

	// contract-test: direct surface=rest_api assertions=ai-decide.failures.distinct,sdk.anonymous.signup-required
	test('disabled isolated free budget reports signup required for skills and JSON or SSE chat', async ({ request }: { request: any }) => {
		// This CI fixture has no configured anonymous budget. Assert that precondition
		// before valid requests so the test can never start real provider inference.
		const availability = await request.get(`${API_URL}/v1/anonymous/free-usage/status`);
		expect(availability.status()).toBe(200);
		expect((await availability.json()).active).toBe(false);
		const decision = await request.post(`${API_URL}/v1/anonymous/apps/ai/skills/decide`, {
			data: decisionInput
		});
		for (const response of [decision, ...await Promise.all(['application/json', 'text/event-stream'].map(Accept =>
			request.post(`${API_URL}/v1/anonymous/chat/stream`, {
				headers: { Accept }, data: { client_chat_id: 'e2e-guest-chat',
					client_message_id: `message-${Accept}`, plaintext_message: 'Hello', message_history: [] }
			})
		))]) {
			expect(response.status()).toBe(429);
			const { detail } = await response.json();
			expect(detail.signup_required).toBe(true);
			expect(detail.message).toMatch(/free allowance/i);
			expect(detail.message).toMatch(/create an account/i);
			expect(detail.message).not.toMatch(/processing failed|inference failed|internal error/i);
		}
	});

	// contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
	test('headerless skill availability uses the disabled shared allowance', async ({ request }: { request: any }) => {
		const status = await request.get(`${API_URL}/v1/anonymous/free-usage/status`);
		expect(status.status()).toBe(200);
		const budget = await status.json();
		expect(budget.active).toBe(false);
		expect(budget.daily_remaining_percent).toBeNull();
		const response = await request.post(`${API_URL}/v1/anonymous/apps/web/skills/search/availability`, {
			data: { requests: [{ query: 'OpenMates' }] }
		});
		expect(response.status()).toBe(200);
		expect((await response.json()).allowed).toBe(false);
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

	// contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
	test('rejects multiple provider requests behind one credit quote', async ({ request }: { request: any }) => {
		const response = await request.post(`${API_URL}/v1/anonymous/apps/web/skills/search`, {
			headers: { 'X-OpenMates-Anonymous-ID': 'e2e-guest-skill-batch' },
			data: { requests: [{ query: 'OpenMates' }, { query: 'OpenMates docs' }] }
		});
		expect(response.status()).toBe(422);
		expect((await response.json()).detail.code).toBe('invalid_request_count');
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
