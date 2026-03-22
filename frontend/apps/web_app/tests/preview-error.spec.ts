import { expect, test } from '@playwright/test';

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
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'networkidle' });

	// Wait for the component to attempt to mount and fail.
	// The error may be caught synchronously or asynchronously (within 500ms).
	await page.waitForTimeout(2000);

	// The toolbar should be visible (page loaded successfully)
	await expect(page.locator('.toolbar')).toBeVisible();

	// Should show render error, NOT "Loading component..."
	const loadingVisible = await page.locator('text=Loading component').isVisible().catch(() => false);
	expect(loadingVisible).toBe(false);

	// The render error panel should be displayed
	await expect(page.locator('.render-error')).toBeVisible({ timeout: 5000 });
	await expect(page.locator('.render-error h2')).toHaveText('Render Error');

	// Should have actionable buttons
	await expect(page.locator('.error-btn', { hasText: 'Retry' })).toBeVisible();
	await expect(page.locator('.error-btn', { hasText: 'Edit Props' })).toBeVisible();

	// Should mention creating a .preview.ts file (since BaseAppCard doesn't have one)
	await expect(page.locator('.render-error')).toContainText('.preview.ts');
});

test('retry button re-attempts render after error', async ({ page }) => {
	await page.goto('/dev/preview/cards/BaseAppCard', { waitUntil: 'networkidle' });
	await page.waitForTimeout(2000);

	// Should show render error
	await expect(page.locator('.render-error')).toBeVisible({ timeout: 5000 });

	// Click retry — it should attempt to mount again and fail again
	// (since we haven't provided props)
	await page.locator('.error-btn', { hasText: 'Retry' }).click();
	await page.waitForTimeout(2000);

	// Should still show render error after retry (props are still missing)
	await expect(page.locator('.render-error')).toBeVisible({ timeout: 5000 });
});
