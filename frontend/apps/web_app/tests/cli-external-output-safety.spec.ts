/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Real external retrieval through REST and CLI; model quality is measured separately. */
const { test, expect } = require('./console-monitor');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const { splitApiKeyCredential } = require('../../../packages/openmates-cli/src/crypto');

function fieldValues(value: unknown, field: string): string[] {
	if (!value || typeof value !== 'object') return [];
	if (Array.isArray(value)) return value.flatMap(item => fieldValues(item, field));
	return Object.entries(value).flatMap(([key, nested]) =>
		key === field && typeof nested === 'string' ? [nested] : fieldValues(nested, field));
}

test.describe('External skill output safety', () => {
	test.setTimeout(180_000);
	let apiUrl: string;
	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// contract-test: direct surface=rest_api assertions=app-skills.output.external-semantic,app-skills.output.ascii-always
	test('REST web read preserves benign content and still requires authentication', async ({ request }) => {
		const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
		expect(key, 'CI must provision an API key').toBeTruthy();
		const url = `${apiUrl}/v1/apps/web/skills/read`;
		const input = { requests: [{ url: 'https://example.com' }] };
		const unauthorized = await request.post(url, { data: input });
		expect([401, 403]).toContain(unauthorized.status());
		const response = await request.post(url, {
			data: input,
			headers: { Authorization: `Bearer ${splitApiKeyCredential(key).bearer}` },
			timeout: 90_000
		});
		expect(response.ok()).toBe(true);
		const markdown = fieldValues(await response.json(), 'markdown').join('\n');
		expect(markdown).toContain('documentation examples');
		expect(markdown).not.toContain('[PROMPT INJECTION DETECTED & REMOVED]');
	});

	// contract-test: direct surface=cli assertions=app-skills.output.external-semantic,app-skills.output.batch-equivalent,app-skills.surface.semantic-parity
	test('CLI web read preserves a benign multi-page batch with protection on and off', async () => {
		expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY).toBeTruthy();
		const input = { requests: [
			{ url: 'https://example.com' },
			{ url: 'https://example.org' }
		] };
		const args = ['apps', 'web', 'read', '--input', JSON.stringify(input), '--json'];
		const enabled = await runCli(apiUrl, args, 90_000, { record: false });
		expectCliSuccess(enabled);
		const disabled = await runCli(apiUrl, [...args, '--disable-prompt-injection-protection'], 90_000, { record: false });
		expectCliSuccess(disabled);
		const protectedGroups = parseCliJson(enabled).data?.results;
		const originalGroups = parseCliJson(disabled).data?.results;
		expect(Array.isArray(protectedGroups)).toBe(true);
		expect(Array.isArray(originalGroups)).toBe(true);
		expect(protectedGroups).toHaveLength(2);
		expect(originalGroups).toHaveLength(2);
		for (let index = 0; index < 2; index += 1) {
			expect(protectedGroups[index].results).toHaveLength(1);
			expect(originalGroups[index].results).toHaveLength(1);
			const protectedPage = protectedGroups[index].results[0];
			const originalPage = originalGroups[index].results[0];
			expect(protectedPage.url).toBe(originalPage.url);
			expect(protectedPage.title).toContain('Example Domain');
			expect(protectedPage.title).toBe(originalPage.title);
			expect(protectedPage.markdown).toContain('documentation examples');
			expect(protectedPage.markdown).toBe(originalPage.markdown);
			expect(protectedPage.markdown).not.toContain('[PROMPT INJECTION DETECTED & REMOVED]');
		}
	});

	// contract-test: direct surface=cli assertions=app-skills.output.external-semantic,app-skills.surface.semantic-parity
	for (const video of ['fhoJK02oD_E', 'CXYt9wzX3kg']) {
		test(`CLI preserves original benign transcript ${video} with protection on and off`, async () => {
			expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY).toBeTruthy();
			const args = ['apps', 'videos', 'get_transcript', '--url', `https://www.youtube.com/watch?v=${video}`, '--no-download', '--json'];
			const enabled = await runCli(apiUrl, args, 90_000, { record: false });
			expectCliSuccess(enabled);
			const disabled = await runCli(apiUrl, [...args, '--disable-prompt-injection-protection'], 90_000, { record: false });
			expectCliSuccess(disabled);
			const original = fieldValues(parseCliJson(disabled), 'transcript');
			const protectedText = fieldValues(parseCliJson(enabled), 'transcript');
			expect(original.length).toBeGreaterThan(0);
			expect(original.join('').length).toBeGreaterThan(1000);
			expect(protectedText).toEqual(original);
			expect(protectedText.join('')).not.toContain('[PROMPT INJECTION DETECTED & REMOVED]');
		});
	}
});
