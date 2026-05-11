import { expect, test } from './helpers/cookie-audit';
/**
 * Tests for component preview loading.
 * BaseAppCard used to crash without preview props; the current preview route
 * should either render the component or an error panel, but never get stuck in
 * the loading state.
 */

test('loads component preview route without getting stuck', async ({ page }) => {
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'domcontentloaded' });

	// Wait for the component to attempt to mount and fail.
	// The error may be caught synchronously or asynchronously (within 500ms).
	await page.waitForTimeout(2000);

	// The toolbar should be visible (page loaded successfully)
	await expect(page.getByTestId('preview-toolbar')).toBeVisible();

	// Should show render error, NOT "Loading component..."
	const loadingVisible = await page.locator('text=Loading component').isVisible().catch(() => false);
	expect(loadingVisible).toBe(false);

	const hasErrorPanel = await page.getByTestId('render-error').isVisible().catch(() => false);
	const hasPreviewContent = await page.locator('main').isVisible().catch(() => false);
	expect(hasErrorPanel || hasPreviewContent).toBe(true);
});

test('preview toolbar remains available after preview load', async ({ page }) => {
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);

	await expect(page.getByTestId('preview-toolbar')).toBeVisible();
	const loadingVisible = await page.locator('text=Loading component').isVisible().catch(() => false);
	expect(loadingVisible).toBe(false);
});
