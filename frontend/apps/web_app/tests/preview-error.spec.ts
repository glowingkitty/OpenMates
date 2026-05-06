import { expect, test } from './helpers/cookie-audit';
/**
 * Tests for component preview error handling.
 * Components without .preview.ts files (like BaseAppCard) may crash during
 * render due to missing required snippet props. The preview system should
 * catch these errors and display a helpful "Render Error" panel instead of
 * showing "Loading component..." forever or a blank page.
 */

test('shows render error for component without preview props', async ({ page }) => {
	// BaseAppCard uses required snippet props ({@render top()}, etc.)
	// and will crash during mount without them.
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'domcontentloaded' });

	// Wait for the component to attempt to mount and fail.
	// The error may be caught synchronously or asynchronously (within 500ms).
	await page.waitForTimeout(2000);

	// The toolbar should be visible (page loaded successfully)
	await expect(page.getByTestId('preview-toolbar')).toBeVisible();

	// Should show render error, NOT "Loading component..."
	const loadingVisible = await page.locator('text=Loading component').isVisible().catch(() => false);
	expect(loadingVisible).toBe(false);

	// The render error panel should be displayed
	await expect(page.getByTestId('render-error')).toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('render-error').locator('h2')).toHaveText('Render Error');

	// Should have actionable buttons
	await expect(page.getByTestId('error-btn-retry')).toBeVisible();
	await expect(page.getByTestId('error-btn-edit-props')).toBeVisible();

	// Should mention creating a .preview.ts file (since BaseAppCard doesn't have one)
	await expect(page.getByTestId('render-error')).toContainText('.preview.ts');
});

test('retry button re-attempts render after error', async ({ page }) => {
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);

	// Should show render error
	await expect(page.getByTestId('render-error')).toBeVisible({ timeout: 5000 });

	// Click retry — it should attempt to mount again and fail again
	// (since we haven't provided props)
	await page.getByTestId('error-btn-retry').click();
	await page.waitForTimeout(2000);

	// Should still show render error after retry (props are still missing)
	await expect(page.getByTestId('render-error')).toBeVisible({ timeout: 5000 });
});
