/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers in this directory expose CommonJS exports. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

function deriveApiUrl(baseUrl: string): string {
	const explicitApiUrl = process.env.PLAYWRIGHT_TEST_API_URL;
	if (explicitApiUrl) return explicitApiUrl;

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

test.describe('Feature availability', () => {
	test('default-disabled platform workspaces stay hidden until explicitly enabled', async ({ page }) => {
		test.setTimeout(120000);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const availabilityResponse = await page.request.get(`${apiUrl}/v1/features/availability`);
		expect(availabilityResponse.ok()).toBe(true);
		const availability = await availabilityResponse.json();
		const disabled = availability.disabled ?? [];

		expect(disabled).toContain('platform:projects');
		expect(disabled).toContain('platform:plans');
		expect(disabled).toContain('platform:workflows');
		expect(disabled).toContain('platform:tasks');
		expect(disabled).not.toContain('app:web');

		await page.goto('/', { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});

		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('projects-nav-link')).toHaveCount(0);
		await expect(page.getByTestId('plans-nav-link')).toHaveCount(0);
		await expect(page.getByTestId('workflows-nav-link')).toHaveCount(0);
		await expect(page.getByTestId('tasks-nav-link')).toHaveCount(0);

		await page.goto('/projects', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('projects-feature-disabled')).toBeVisible({ timeout: 30000 });

		await page.goto('/plans', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('plans-feature-disabled')).toBeVisible({ timeout: 30000 });

		await page.goto('/workflows', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('workflows-feature-disabled')).toBeVisible({ timeout: 30000 });

		await page.goto('/tasks', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-feature-disabled')).toBeVisible({ timeout: 30000 });
	});
});
