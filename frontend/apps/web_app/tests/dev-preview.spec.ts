import { expect, test } from './helpers/cookie-audit';
// contract-test-file: tooling

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const COMPONENT_CAPTURE_PROOF = defineVideoProof({
	id: 'url-configured-component-capture',
	title: 'URL-configured component capture',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'configured-preview',
			text: 'Open a component preview URL with custom text, width, theme, and background settings.',
			checkpoint: 'configured-preview',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'capture-ready',
			text: 'The selected component renders by itself on the requested background, ready for a screenshot.',
			checkpoint: 'configured-preview',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'component-only',
			checkpoint: 'configured-preview',
			visual: 'Only the configured notification and its custom background are visible, without preview controls.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'custom-content',
			checkpoint: 'configured-preview',
			visual: 'The URL-provided notification title and message are readable.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

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
		await expect(page.getByTestId('component-count')).toBeVisible();

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
		await expect(page.getByTestId('preview-toolbar')).toBeVisible();

		// Back link should be present (using specific selector to avoid strict mode)
		await expect(page.getByTestId('preview-back-link')).toBeVisible();

		// Component name should appear in breadcrumb
		await expect(page.getByTestId('breadcrumb-name')).toHaveText('WebSearchEmbedPreview');

		// Status bar should show the component file name
		await expect(page.getByTestId('preview-status-bar')).toBeVisible();
	});

	test('client-side navigation from index to component works', async ({ page }) => {
		await page.goto('/dev/preview', { waitUntil: 'networkidle' });
		await page.waitForTimeout(2000);

		// Search for a known component
		const searchInput = page.locator('input[placeholder="Search components..."]');
		await searchInput.fill('WebSearchEmbedPreview');
		await page.waitForTimeout(500);

		// Click on the component link
		const componentLink = page.getByTestId('tree-file').filter({ hasText: 'WebSearchEmbedPreview' });
		await expect(componentLink).toBeVisible();
		await componentLink.click();

		// Should navigate to the component preview with toolbar
		await expect(page.getByTestId('preview-toolbar')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('breadcrumb-name')).toHaveText('WebSearchEmbedPreview');
	});

	test('capture URL renders only the configured component on a custom background', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(COMPONENT_CAPTURE_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		const props = JSON.stringify({
			notification: {
				id: 'capture-notification',
				type: 'warning',
				title: 'URL configured warning',
				message: 'Rendered from query parameters.',
				duration: 0,
				dismissible: true
			}
		});
		const params = new URLSearchParams({
			variant: 'warning',
			theme: 'light',
			background: '#dbeafe',
			width: '420',
			props,
			chrome: '0'
		});

		const response = await page.goto(`/dev/preview/Notification?${params}`, {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);

		const canvas = page.getByTestId('component-preview-canvas');
		await expect(canvas).toHaveAttribute('data-preview-ready', 'true');
		await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
		await expect(page.getByTestId('preview-status-bar')).toHaveCount(0);
		await expect(canvas.getByText('URL configured warning')).toBeVisible();
		await expect(canvas.getByText('Rendered from query parameters.')).toBeVisible();

		const canvasBackground = await canvas.evaluate(
			(element) => window.getComputedStyle(element).backgroundColor
		);
		expect(canvasBackground).toBe('rgb(219, 234, 254)');
		await expect(page.getByTestId('component-preview-viewport')).toHaveCSS('max-width', '420px');
		expect(await page.locator('html').getAttribute('data-theme')).toBe('light');
		const canvasBox = await canvas.boundingBox();
		const viewportBox = await page.getByTestId('component-preview-viewport').boundingBox();
		expect(canvasBox).not.toBeNull();
		expect(viewportBox).not.toBeNull();
		expect(Math.abs(viewportBox!.x + viewportBox!.width / 2 - (canvasBox!.x + canvasBox!.width / 2))).toBeLessThan(2);
		expect(Math.abs(viewportBox!.y + viewportBox!.height / 2 - (canvasBox!.y + canvasBox!.height / 2))).toBeLessThan(2);
		await proof.checkpoint('configured-preview');
	});

	test('client-side preview navigation reapplies URL configuration', async ({ page }) => {
		await page.goto('/dev/preview/Notification?background=%23dbeafe', {
			waitUntil: 'networkidle'
		});
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true'
		);

		await page.evaluate(() => {
			const link = document.createElement('a');
			link.href =
				'/dev/preview/interactive_questions/InteractiveQuestionContainer?variant=input_form&background=%23dbeafe&width=768&chrome=0';
			link.dataset.testid = 'preview-spa-navigation';
			link.textContent = 'Open configured preview';
			document.body.appendChild(link);
		});
		await page.getByTestId('preview-spa-navigation').click();

		const canvas = page.getByTestId('component-preview-canvas');
		await expect(canvas).toHaveAttribute('data-preview-ready', 'true');
		await expect(canvas.getByText('Please introduce yourself to the assistant')).toBeVisible();
		await expect(page.getByTestId('component-preview-viewport')).toHaveCSS('max-width', '768px');
		await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
		const canvasBackground = await canvas.evaluate(
			(element) => window.getComputedStyle(element).backgroundColor
		);
		expect(canvasBackground).toBe('rgb(219, 234, 254)');
	});

	test('website fullscreen highlights source quote text', async ({ page }) => {
		const response = await page.goto('/dev/preview/embeds/web', { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const websiteSection = page.getByTestId('skill-section').filter({ has: page.getByTestId('skill-label').filter({ hasText: 'Website' }) });
		await expect(websiteSection).toBeVisible({ timeout: 15000 });

		await websiteSection.getByRole('button', { name: 'withHighlightedQuote' }).click();
		const highlight = websiteSection.getByTestId('embed-source-text-highlight');
		await expect(highlight).toBeVisible({ timeout: 10000 });
		await expect(highlight).toHaveText('Svelte writes code that updates the DOM when state changes');

		const styles = await highlight.evaluate((el: HTMLElement) => {
			const computed = window.getComputedStyle(el);
			return {
				backgroundColor: computed.backgroundColor,
				boxShadow: computed.boxShadow,
			};
		});
		expect(styles.backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
		expect(styles.boxShadow).not.toBe('none');
	});
});
