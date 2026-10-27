import { expect, test } from './helpers/cookie-audit';

// contract-test: tooling
test('Brotli protection preserves bootstrap, reload, login and public share routes', async ({ page }) => {
	test.setTimeout(120000);
	const exceptions: string[] = [];
	page.on('pageerror', (error) => exceptions.push(error.message));
	const environment = await page.request.get('/_app/env.js');
	expect(environment.ok()).toBe(true);
	expect(environment.headers()['content-type']).toMatch(/(?:java|ecma)script/);
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 30000 });
	await page.waitForLoadState('networkidle');
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 30000 });
	await page.waitForLoadState('networkidle');
	await page.getByTestId('header-login-signup-btn').click();
	await expect(page.getByTestId('login-tabs')).toBeVisible({ timeout: 10000 });
	await page.getByTestId('tab-login').click();
	await expect(page.locator('#login-email-input')).toBeEditable({ timeout: 10000 });

	const unknownId = '00000000-0000-4000-8000-000000000001';
	for (const path of ['/s/abc123', `/share/chat/${unknownId}`, `/share/embed/${unknownId}`]) {
		// These paths colocate +page.svelte with +server.ts. HTML negotiation
		// selects the page renderer; wildcard negotiation selects the endpoint.
		const metadata = await page.request.get(path, { headers: { accept: '*/*' } });
		expect(metadata.status(), `Public metadata page ${path}`).toBe(200);
		expect(await metadata.text()).toContain('property="og:title"');
		// Harmless plain bytes with an encoding header, never an exploit payload.
		const encoded = await page.request.post(path, { data: '{}', headers: { 'content-encoding': 'br' } });
		expect(encoded.status(), `Encoded body must be rejected for ${path}`).toBe(415);
	}
	expect(exceptions).toEqual([]);
});
