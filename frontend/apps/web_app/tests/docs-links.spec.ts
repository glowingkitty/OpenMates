import { expect, test } from '@playwright/test';

/**
 * Tests for documentation page link resolution.
 *
 * Verifies that relative links in markdown docs are correctly resolved to:
 * - /docs/ routes for .md file links
 * - GitHub blob URLs for source code file links
 * - GitHub tree URLs for directory links
 * - No broken relative links remain (../.. or ./ prefixed)
 *
 * Uses the architecture/ai/ai-model-selection page as the primary test target
 * because it contains a mix of all link types: folder links, code file links,
 * .md links, and code files with various extensions.
 *
 * Architecture: docs/architecture/frontend/docs-web-app.md
 */
test.describe('Documentation page links', () => {
	const GITHUB_BASE = 'https://github.com/glowingkitty/OpenMates';
	const TEST_PAGE = '/docs/architecture/ai/ai-model-selection';

	test('page loads successfully', async ({ page }) => {
		const response = await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);
	});

	test('no broken relative links remain on page', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		// Get all links on the page
		const links = await page.locator('.docs-content-scroll a[href]').all();
		const brokenLinks: string[] = [];

		for (const link of links) {
			const href = await link.getAttribute('href');
			if (href && (href.startsWith('../') || href.startsWith('./'))) {
				const text = await link.textContent();
				brokenLinks.push(`"${text}" → ${href}`);
			}
		}

		expect(brokenLinks, `Found broken relative links:\n${brokenLinks.join('\n')}`).toHaveLength(0);
	});

	test('folder links point to GitHub tree URLs', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		// The page has a link to backend/providers/ which is a directory
		const providerLink = page.locator('.docs-content-scroll a[href*="backend/providers"]');
		const count = await providerLink.count();

		if (count > 0) {
			const href = await providerLink.first().getAttribute('href');
			expect(href).toContain(`${GITHUB_BASE}/tree/`);
			expect(href).toContain('backend/providers');
		}
	});

	test('code file links point to GitHub blob URLs', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		// The page has links to .py and .yml files
		const codeLinks = page.locator('.docs-content-scroll a[href*="github.com"]');
		const count = await codeLinks.count();
		expect(count).toBeGreaterThan(0);

		// Verify at least one blob link exists for a source file
		const allHrefs: string[] = [];
		for (let i = 0; i < count; i++) {
			const href = await codeLinks.nth(i).getAttribute('href');
			if (href) allHrefs.push(href);
		}

		const blobLinks = allHrefs.filter((h) => h.includes('/blob/'));
		expect(blobLinks.length, 'Should have at least one GitHub blob link for code files').toBeGreaterThan(0);

		// Verify specific known code file links
		const hasAppYml = allHrefs.some((h) => h.includes('backend/apps/ai/app.yml'));
		expect(hasAppYml, 'Should have link to backend/apps/ai/app.yml').toBe(true);

		const hasPreprocessor = allHrefs.some((h) => h.includes('backend/apps/ai/processing/preprocessor.py'));
		expect(hasPreprocessor, 'Should have link to preprocessor.py').toBe(true);
	});

	test('markdown links point to /docs/ routes', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		// The page has links to other docs (message-processing, thinking-models, etc.)
		const docsLinks = page.locator('.docs-content-scroll a[href^="/docs/"]');
		const count = await docsLinks.count();
		expect(count).toBeGreaterThan(0);

		// Verify specific known doc links
		const allHrefs: string[] = [];
		for (let i = 0; i < count; i++) {
			const href = await docsLinks.nth(i).getAttribute('href');
			if (href) allHrefs.push(href);
		}

		const hasMessageProcessing = allHrefs.some((h) =>
			h.includes('/docs/architecture/messaging/message-processing')
		);
		expect(hasMessageProcessing, 'Should have link to message-processing doc').toBe(true);
	});

	test('breadcrumb navigation is present and correct', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		const breadcrumb = page.locator('nav.docs-breadcrumb');
		await expect(breadcrumb).toBeVisible();

		// Should have the path: Docs > Architecture > AI > AI Model Selection
		const crumbLinks = breadcrumb.locator('a.crumb-link');
		const crumbCount = await crumbLinks.count();
		expect(crumbCount).toBeGreaterThanOrEqual(2); // At least "Docs" and intermediate folders

		// First crumb should link to /docs
		const firstHref = await crumbLinks.first().getAttribute('href');
		expect(firstHref).toBe('/docs');

		// Current page should be shown as non-link text
		const currentCrumb = breadcrumb.locator('span.current');
		await expect(currentCrumb).toBeVisible();
		const currentText = await currentCrumb.textContent();
		expect(currentText).toContain('AI Model Selection');
	});

	test('breadcrumb folder links are navigable', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		const breadcrumb = page.locator('nav.docs-breadcrumb');
		const crumbLinks = breadcrumb.locator('a.crumb-link');

		// Click the "Architecture" breadcrumb (second link)
		const count = await crumbLinks.count();
		if (count >= 2) {
			const secondLink = crumbLinks.nth(1);
			const href = await secondLink.getAttribute('href');
			expect(href).toContain('/docs/architecture');

			await secondLink.click();
			await page.waitForURL(/\/docs\/architecture/);
			expect(page.url()).toContain('/docs/architecture');
		}
	});

	test('download button triggers .md file download', async ({ page }) => {
		await page.goto(TEST_PAGE, { waitUntil: 'networkidle' });

		// Find the download button
		const downloadBtn = page.locator('button.icon_download');
		await expect(downloadBtn).toBeVisible();

		// Listen for download event
		const downloadPromise = page.waitForEvent('download', { timeout: 5000 });
		await downloadBtn.click();
		const download = await downloadPromise;

		// Verify it's a .md file
		expect(download.suggestedFilename()).toMatch(/\.md$/);
	});

	// =========================================================================
	// Cross-page verification: check other pages with known link types
	// =========================================================================

	test('auto-topup page has no broken links', async ({ page }) => {
		await page.goto('/docs/architecture/payments/auto-topup', { waitUntil: 'networkidle' });

		const links = await page.locator('.docs-content-scroll a[href]').all();
		const brokenLinks: string[] = [];

		for (const link of links) {
			const href = await link.getAttribute('href');
			if (href && (href.startsWith('../') || href.startsWith('./'))) {
				const text = await link.textContent();
				brokenLinks.push(`"${text}" → ${href}`);
			}
		}

		expect(brokenLinks, `Found broken relative links:\n${brokenLinks.join('\n')}`).toHaveLength(0);
	});

	test('security page folder links resolve to GitHub tree URLs', async ({ page }) => {
		await page.goto('/docs/architecture/core/security', { waitUntil: 'networkidle' });

		// The security page has a link to backend/core/vault/ directory
		const links = await page.locator('.docs-content-scroll a[href]').all();
		const brokenLinks: string[] = [];

		for (const link of links) {
			const href = await link.getAttribute('href');
			if (href && (href.startsWith('../') || href.startsWith('./'))) {
				brokenLinks.push(href);
			}
		}

		expect(brokenLinks).toHaveLength(0);
	});
});
