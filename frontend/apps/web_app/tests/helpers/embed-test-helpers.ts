/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared embed assertion helpers for Playwright E2E tests.
 *
 * Composable helpers for waiting on embeds, opening fullscreen,
 * verifying search grids, and closing overlays.
 *
 * Usage:
 *   const { waitForEmbedFinished, openFullscreen, verifySearchGrid, closeFullscreen } = require('./helpers/embed-test-helpers');
 *
 * Architecture context: docs/architecture/embeds.md
 */
export {};

const { expect } = require('@playwright/test');

// ── Display types expected on /dev/preview/embeds/{app} pages ───────────────

const EXPECTED_DT_HEADINGS = [
	'Inline Link',
	'Quote Block',
	'Group — Small',
	'Fullscreen'
];

/**
 * Verify the /dev/preview/embeds/{app} page renders correctly.
 * Checks: page loads, sections load, display types present, at least one embed finished.
 */
async function verifyEmbedPreviewPage(
	page: any,
	app: string,
	logCheckpoint: (message: string) => void
): Promise<void> {
	const response = await page.goto(`/dev/preview/embeds/${app}`, {
		waitUntil: 'networkidle'
	});
	expect(response?.status()).toBe(200);
	logCheckpoint(`Navigated to /dev/preview/embeds/${app}`);

	// Wait for SvelteKit hydration
	await page.waitForTimeout(3000);

	// Not an unknown app
	await expect(page.locator('div.unknown-app')).not.toBeVisible();

	// App title visible
	await expect(page.locator('h1.app-title')).toBeVisible();

	// All sections finish loading
	await expect(async () => {
		const loadingCount = await page.locator('p.section-loading').count();
		expect(loadingCount).toBe(0);
	}).toPass({ timeout: 20_000 });
	logCheckpoint('All sections loaded');

	// No component load errors
	const sectionErrors = await page.locator('p.section-error').count();
	expect(sectionErrors, `${app}: found ${sectionErrors} section load error(s)`).toBe(0);

	// All skill sections have expected display types
	const skillSections = page.locator('section.skill-section');
	const sectionCount = await skillSections.count();
	expect(sectionCount, `${app}: expected at least 1 skill section`).toBeGreaterThan(0);

	for (let i = 0; i < sectionCount; i++) {
		const section = skillSections.nth(i);
		const skillLabel = await section.locator('h2.skill-label').textContent();

		for (const heading of EXPECTED_DT_HEADINGS) {
			const dtLocator = section.locator(`h3.dt-heading:has-text("${heading}")`);
			const count = await dtLocator.count();
			expect(count, `${app}/${skillLabel}: missing display type "${heading}"`).toBeGreaterThan(0);
		}
	}
	logCheckpoint('Display types verified');

	// At least one embed reached "finished" status
	const finishedEmbed = page.locator('.unified-embed-preview[data-status="finished"]');
	const finishedCount = await finishedEmbed.count();
	expect(finishedCount, `${app}: no embeds reached "finished" status`).toBeGreaterThan(0);
	logCheckpoint(`${finishedCount} embed(s) finished`);

	// No rendering artifacts
	const bodyText = await page.locator('body').innerText();
	expect(bodyText).not.toContain('[object Object]');
	expect(bodyText).not.toContain('undefined');
	logCheckpoint('No rendering artifacts');
}

/**
 * Wait for a specific embed to reach "finished" status in the chat.
 * Returns the locator for the finished embed.
 */
async function waitForEmbedFinished(
	page: any,
	appId: string,
	skillId: string,
	timeout = 90000
): Promise<any> {
	const selector = `.unified-embed-preview[data-app-id="${appId}"][data-skill-id="${skillId}"][data-status="finished"]`;
	const embed = page.locator(selector);
	await expect(embed.first()).toBeVisible({ timeout });
	return embed.first();
}

/**
 * Open the fullscreen overlay by clicking on an embed preview.
 * Returns the fullscreen overlay locator.
 */
async function openFullscreen(page: any, embedLocator: any): Promise<any> {
	await embedLocator.click();
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500); // animation
	return fullscreenOverlay;
}

/**
 * Verify the search results grid in a fullscreen overlay.
 * Checks that at least `minResults` result cards are present.
 */
async function verifySearchGrid(
	fullscreenOverlay: any,
	minResults = 1,
	timeout = 60000
): Promise<any> {
	const resultsGrid = fullscreenOverlay.locator('.search-template-grid');
	await expect(resultsGrid).toBeVisible({ timeout });

	const resultCards = resultsGrid.locator('.unified-embed-preview');
	await expect(async () => {
		const count = await resultCards.count();
		expect(count).toBeGreaterThanOrEqual(minResults);
	}).toPass({ timeout });

	return resultCards;
}

/**
 * Close the fullscreen overlay via the minimize button.
 * Verifies the overlay is no longer visible.
 */
async function closeFullscreen(page: any, fullscreenOverlay: any): Promise<void> {
	const minimizeButton = fullscreenOverlay.locator('.minimize-button');
	const hasMinimize = await minimizeButton.isVisible({ timeout: 3000 }).catch(() => false);

	if (hasMinimize) {
		await minimizeButton.click();
	} else {
		await page.keyboard.press('Escape');
	}

	await page.waitForTimeout(500);
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
}

module.exports = {
	EXPECTED_DT_HEADINGS,
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
};
