import { expect, test } from '@playwright/test';

/**
 * Tests for the /dev/preview/ component preview system.
 * Runs against the deployed dev instance (app.dev.openmates.org).
 *
 * These tests verify:
 * 1. The preview index page loads and shows the component tree
 * 2. Direct-linking to a specific component preview works (no MIME errors)
 * 3. Client-side navigation from index to a component works
 */
test.describe('Component Preview System', () => {
	test('preview index page loads and shows component tree', async ({ page }) => {
		const pageErrors: string[] = [];
		page.on('pageerror', (err) => {
			pageErrors.push(`${err.name}: ${err.message}`);
		});

		const response = await page.goto('/dev/preview', { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		// Wait for SvelteKit client hydration
		await page.waitForTimeout(3000);

		// Dev gate should not block on dev domain
		const notAvailable = await page.locator('text=Not Available').isVisible().catch(() => false);
		expect(notAvailable).toBe(false);

		// Component Preview heading should be visible
		await expect(page.locator('h1:has-text("Component Preview")')).toBeVisible();

		// Should show component count (e.g. "273 components")
		await expect(page.locator('.component-count')).toBeVisible();

		// Search bar should be present
		await expect(page.locator('input[placeholder="Search components..."]')).toBeVisible();

		// Should have no JS errors
		expect(pageErrors).toHaveLength(0);
	});

	test('direct link to component preview loads without MIME errors', async ({ page }) => {
		// Track module loading errors (the symptom of the blank page bug)
		const moduleErrors: string[] = [];
		page.on('console', (msg) => {
			if (msg.type() === 'error' && msg.text().includes('MIME type')) {
				moduleErrors.push(msg.text());
			}
		});

		const response = await page.goto('/dev/preview/embeds/web/WebSearchEmbedPreview', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);

		// Wait for SvelteKit client hydration
		await page.waitForTimeout(3000);

		// CRITICAL: Should have NO MIME type errors (this was the blank page bug)
		expect(moduleErrors).toHaveLength(0);

		// The preview page UI should be present (toolbar with back link)
		await expect(page.locator('.toolbar')).toBeVisible();

		// Back link should be present (using specific selector to avoid strict mode)
		await expect(page.locator('.back-link')).toBeVisible();

		// Component name should appear in breadcrumb
		await expect(page.locator('.breadcrumb-name')).toHaveText('WebSearchEmbedPreview');

		// Status bar should show the component file name
		await expect(page.locator('.status-bar')).toBeVisible();
	});

	test('client-side navigation from index to component works', async ({ page }) => {
		await page.goto('/dev/preview', { waitUntil: 'networkidle' });
		await page.waitForTimeout(2000);

		// Search for a known component
		const searchInput = page.locator('input[placeholder="Search components..."]');
		await searchInput.fill('WebSearchEmbedPreview');
		await page.waitForTimeout(500);

		// Click on the component link
		const componentLink = page.locator('a.tree-file:has-text("WebSearchEmbedPreview")');
		await expect(componentLink).toBeVisible();
		await componentLink.click();

		// Should navigate to the component preview with toolbar
		await expect(page.locator('.toolbar')).toBeVisible({ timeout: 10000 });
		await expect(page.locator('.breadcrumb-name')).toHaveText('WebSearchEmbedPreview');
	});
});
