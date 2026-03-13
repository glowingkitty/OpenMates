import { expect, test } from '@playwright/test';

/**
 * Verifies that the deployed app root loads without browser error logs.
 * This guards against service worker bootstrap regressions that break first paint.
 * Architecture context: docs/architecture/logging.md
 * Bug reference: workbox non-precached-url thrown during app bootstrap.
 * Test reference: run via scripts/run-tests.sh --suite playwright.
 */

test('app root loads without console errors', async ({ page }) => {
	test.setTimeout(120000);
	test.slow();

	const errorLogs: string[] = [];

	page.on('console', (message) => {
		if (message.type() === 'error') {
			errorLogs.push(`[console.error] ${message.text()}`);
		}
	});

	page.on('pageerror', (error) => {
		const stack = error.stack ? `\n${error.stack}` : '';
		errorLogs.push(`[pageerror] ${error.message}${stack}`);
	});

	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	await page.waitForTimeout(3000);

	await expect(page).toHaveURL(/https?:\/\/.+/);

	if (errorLogs.length > 0) {
		console.error('Captured error logs during app load:');
		for (const line of errorLogs) {
			console.error(line);
		}
	}

	expect(errorLogs, `Expected zero browser errors, got ${errorLogs.length}`).toEqual([]);
});
