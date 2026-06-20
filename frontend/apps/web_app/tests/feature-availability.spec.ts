import { expect, test } from './helpers/cookie-audit';

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		// Fall through to the production API default.
	}
	return 'https://api.openmates.org';
}

test.describe('Feature availability', () => {
	test('default-disabled platform features are hidden and direct projects route is blocked', async ({ page }) => {
		test.setTimeout(120000);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const availabilityResponse = await page.request.get(`${apiUrl}/v1/features/availability`);
		expect(availabilityResponse.ok()).toBe(true);
		const availability = await availabilityResponse.json();
		const projects = availability.features.find((feature: { id?: string }) => feature.id === 'platform:projects');
		const workflows = availability.features.find((feature: { id?: string }) => feature.id === 'platform:workflows');
		const tasks = availability.features.find((feature: { id?: string }) => feature.id === 'platform:tasks');

		expect(projects?.enabled).toBe(false);
		expect(workflows?.enabled).toBe(false);
		expect(tasks?.enabled).toBe(false);

		await page.goto('/projects', { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('projects-feature-disabled')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('projects-page')).toHaveCount(0);
		await expect(page.getByTestId('projects-nav-link')).toHaveCount(0);
		await expect(page.getByTestId('workflows-nav-link')).toHaveCount(0);
		await expect(page.getByTestId('tasks-nav-link')).toHaveCount(0);
	});
});
