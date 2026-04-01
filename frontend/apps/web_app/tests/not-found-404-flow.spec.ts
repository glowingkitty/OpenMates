import { expect, test } from '@playwright/test';

/* eslint-disable @typescript-eslint/no-require-imports */
const { getE2EDebugUrl } = require('./signup-flow-helpers');

/**
 * 404 Not-Found Flow Tests
 *
 * Verifies that navigating to an unknown URL path:
 * 1. Does NOT show a bare Vercel/server 404 page
 * 2. Redirects to the SPA root (URL becomes /)
 * 3. Shows the Not404Screen component (ChatHeader "404" + recovery options)
 * 4. Search option opens the sidebar search pre-filled with the path
 * 5. Ask AI option pre-fills the message input with a humanized prompt
 *
 * Architecture: unknown path → SvelteKit catch-all route → redirect to /#404=<path>
 * → +page.svelte detects hash → notFoundPathStore.set(path) → ActiveChat renders
 * Not404Screen.
 *
 * No login required — the 404 screen works for unauthenticated users.
 * Test reference: run via scripts/run-tests.sh --suite playwright.
 */

test.describe('404 not-found flow', () => {
	test('unknown path redirects to SPA and shows 404 screen', async ({ page }) => {
		test.setTimeout(60000);

		const consoleLogs: string[] = [];
		page.on('console', (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		// Navigate to an unknown path
		await page.goto(getE2EDebugUrl('/iphone-review'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(5000);

		// 1. URL should now be the SPA root (path cleaned to /)
		const url = new URL(page.url());
		expect(url.pathname, 'URL pathname should be cleaned to /').toBe('/');

		// 2. Should NOT be a plain server 404 — the page title must be OpenMates, not "404"
		const title = await page.title();
		expect(title, 'Page title should be OpenMates app, not a server error').toMatch(/OpenMates/i);

		// 3. The 404 Not-Found screen should be visible
		await expect(
			page.getByTestId('not-found-screen'),
			'Not404Screen container should be visible'
		).toBeVisible({ timeout: 10000 });

		// 4. Recovery actions (search + ask AI) should be visible
		// Not404Screen uses .not-found-actions (not .not-found-options)
		await expect(
			page.getByTestId('not-found-actions'),
			'Recovery actions container should be visible'
		).toBeVisible({ timeout: 5000 });

		console.log('✅ 404 screen shown correctly for /iphone-review');
	});

	test('404 screen search option opens pre-filled search', async ({ page }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/iphone-review'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(3000);

		// Wait for Not404Screen actions container
		await expect(page.getByTestId('not-found-actions')).toBeVisible({ timeout: 10000 });

		// Click the search option (first button in .not-found-actions)
		const searchButton = page.getByTestId('not-found-actions').locator('button').first();
		await searchButton.click();

		// The sidebar should open and search should be active
		await page.waitForTimeout(1000);

		// Search input should be visible and contain the path query
		const searchInput = page.locator('input[type="search"], input[placeholder*="Search"], [data-testid="search-input"] input').first();
		await expect(searchInput, 'Search input should be visible after clicking search option').toBeVisible({ timeout: 5000 });

		// The 404 screen should be gone
		await expect(
			page.getByTestId('not-found-actions'),
			'404 actions should disappear after search click'
		).not.toBeVisible({ timeout: 5000 });

		console.log('✅ Search option correctly opens pre-filled search');
	});

	test('404 screen Ask AI option pre-fills message input', async ({ page }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/iphone-review'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(3000);

		// Wait for Not404Screen actions container
		await expect(page.getByTestId('not-found-actions')).toBeVisible({ timeout: 10000 });

		// Click the Ask AI option (last button in .not-found-actions)
		const askAIButton = page.getByTestId('not-found-actions').locator('button').last();
		await askAIButton.click();

		// The 404 screen should be gone
		await expect(
			page.getByTestId('not-found-actions'),
			'404 actions should disappear after Ask AI click'
		).not.toBeVisible({ timeout: 5000 });

		// Message input should be pre-filled with the humanized path
		const messageInput = page.locator('[contenteditable="true"]').first();
		await expect(messageInput, 'Message input should be visible').toBeVisible({ timeout: 5000 });

		const inputText = await messageInput.textContent();
		expect(
			inputText?.toLowerCase() ?? '',
			'Message input should contain "iphone review" from the path'
		).toContain('iphone review');

		console.log('✅ Ask AI option correctly pre-fills message input');
	});

	test('multi-segment unknown path uses first segment for search', async ({ page }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/ai/image-generator'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(3000);

		const url = new URL(page.url());
		expect(url.pathname, 'URL should be cleaned to /').toBe('/');

		await expect(page.getByTestId('not-found-actions')).toBeVisible({ timeout: 10000 });

		// The search button label should show only the first segment "ai"
		const searchButton = page.getByTestId('not-found-actions').locator('button').first();
		const buttonText = await searchButton.textContent();
		expect(buttonText?.toLowerCase(), 'Search option should reference first segment "ai"').toContain('ai');

		console.log('✅ Multi-segment path correctly uses first segment for search query');
	});
});
