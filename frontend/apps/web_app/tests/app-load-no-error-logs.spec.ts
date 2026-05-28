import { expect, test } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { getE2EDebugUrl } = require('./signup-flow-helpers');

/**
 * Verifies that the deployed app root loads without browser error logs.
 * This guards against app bootstrap regressions that break first paint.
 * Architecture context: docs/architecture/logging.md
 * Bug reference: stale service-worker navigation handler broke app bootstrap.
 * Test reference: run via scripts/run-tests.sh --suite playwright.
 */

test('app root loads without console errors', async ({ page }) => {
	test.setTimeout(120000);
	test.slow();

	const errorLogs: string[] = [];
	const attachErrorListeners = (targetPage: typeof page): void => {
		targetPage.on('console', (message) => {
			if (message.type() === 'error') {
				errorLogs.push(`[console.error] ${message.text()}`);
			}
		});

		targetPage.on('pageerror', (error) => {
			const stack = error.stack ? `\n${error.stack}` : '';
			errorLogs.push(`[pageerror] ${error.message}${stack}`);
		});
	};

	attachErrorListeners(page);

	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
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
