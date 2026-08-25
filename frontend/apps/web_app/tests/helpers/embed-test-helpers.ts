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
	await expect(page.getByTestId('unknown-app')).not.toBeVisible();

	// App title visible
	await expect(page.getByTestId('app-title')).toBeVisible();

	// All sections finish loading
	await expect(async () => {
		const loadingCount = await page.getByTestId('section-loading').count();
		expect(loadingCount).toBe(0);
	}).toPass({ timeout: 20_000 });
	logCheckpoint('All sections loaded');

	// No component load errors
	const sectionErrors = await page.getByTestId('section-error').count();
	expect(sectionErrors, `${app}: found ${sectionErrors} section load error(s)`).toBe(0);

	// All skill sections have expected display types
	const skillSections = page.getByTestId('skill-section');
	const sectionCount = await skillSections.count();
	expect(sectionCount, `${app}: expected at least 1 skill section`).toBeGreaterThan(0);

	for (let i = 0; i < sectionCount; i++) {
		const section = skillSections.nth(i);
		const skillLabel = await section.getByTestId('skill-label').textContent();

		for (const heading of EXPECTED_DT_HEADINGS) {
			const dtLocator = section.getByTestId('dt-heading').filter({ hasText: heading });
			const count = await dtLocator.count();
			expect(count, `${app}/${skillLabel}: missing display type "${heading}"`).toBeGreaterThan(0);
		}
	}
	logCheckpoint('Display types verified');

	// At least one embed reached "finished" status
	const finishedEmbed = page.locator('[data-testid="embed-preview"][data-status="finished"]');
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
	const selector = '[data-testid="embed-preview"][data-app-id="' + appId + '"][data-skill-id="' + skillId + '"][data-status="finished"]';
	const embed = page.locator(selector);
	await expect(embed.first()).toBeVisible({ timeout });
	return embed.first();
}

/**
 * Open the fullscreen overlay by clicking on an embed preview.
 * Returns the fullscreen overlay locator.
 */
async function openFullscreen(page: any, embedLocator: any): Promise<any> {
	const overlays = page.getByTestId('embed-fullscreen-overlay');
	const visibleOverlayCount = async (): Promise<number> => {
		let visibleCount = 0;
		for (let index = 0, count = await overlays.count(); index < count; index += 1) {
			if (await overlays.nth(index).isVisible({ timeout: 250 }).catch(() => false)) {
				visibleCount += 1;
			}
		}
		return visibleCount;
	};
	const visibleOverlayCountBeforeOpen = await visibleOverlayCount();
	await expect(async () => {
		if (await visibleOverlayCount() > visibleOverlayCountBeforeOpen) return;
		await dismissVisibleNotifications(page);
		await embedLocator.scrollIntoViewIfNeeded();
		await embedLocator.click();
		await expect(async () => {
			expect(await visibleOverlayCount()).toBeGreaterThan(visibleOverlayCountBeforeOpen);
		}).toPass({ timeout: 1000 });
	}).toPass({ timeout: 10000 });
	let fullscreenOverlay = overlays.last();
	for (let index = await overlays.count() - 1; index >= 0; index -= 1) {
		const candidate = overlays.nth(index);
		if (await candidate.isVisible({ timeout: 250 }).catch(() => false)) {
			fullscreenOverlay = candidate;
			break;
		}
	}
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	return fullscreenOverlay;
}

async function dismissVisibleNotifications(page: any): Promise<void> {
	const dismissButtons = page.getByTestId('notification-dismiss');
	for (let index = await dismissButtons.count() - 1; index >= 0; index -= 1) {
		const button = dismissButtons.nth(index);
		if (await button.isVisible({ timeout: 250 }).catch(() => false)) {
			await button.click({ timeout: 1000 }).catch(() => undefined);
		}
	}

	const chatNotifications = page.getByTestId('chat-notification');
	for (let index = await chatNotifications.count() - 1; index >= 0; index -= 1) {
		const notification = chatNotifications.nth(index);
		if (await notification.isVisible({ timeout: 250 }).catch(() => false)) {
			await notification
				.getByRole('button', { name: 'Dismiss notification' })
				.click({ timeout: 1000 })
				.catch(() => undefined);
		}
	}
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
	const resultsGrid = fullscreenOverlay.getByTestId('search-template-grid');
	await expect(resultsGrid).toBeVisible({ timeout });

	const resultCards = resultsGrid.getByTestId('embed-preview');
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
	const overlays = page.getByTestId('embed-fullscreen-overlay');
	if (!await fullscreenOverlay.isVisible({ timeout: 500 }).catch(() => false)) {
		return;
	}
	const overlayCountBeforeClose = await overlays.count();
	const countVisibleOverlays = async (): Promise<number> => {
		const count = await overlays.count();
		let visible = 0;
		for (let i = 0; i < count; i += 1) {
			if (await overlays.nth(i).isVisible().catch(() => false)) visible += 1;
		}
		return visible;
	};
	const visibleOverlaysBeforeClose = await countVisibleOverlays();
	const clickVisibleMinimize = async (buttons: any): Promise<boolean> => {
		const buttonCount = await buttons.count().catch(() => 0);
		for (let i = buttonCount - 1; i >= 0; i -= 1) {
			const button = buttons.nth(i);
			if (await button.isVisible({ timeout: 500 }).catch(() => false)) {
				if (await button.click({ timeout: 1500 }).then(() => true).catch(() => false)) {
					return true;
				}
			}
		}
		return false;
	};

	const closedViaButton = await clickVisibleMinimize(page.getByTestId('embed-minimize'))
		|| await clickVisibleMinimize(fullscreenOverlay.getByTestId('embed-minimize'));
	if (!closedViaButton) {
		await page.keyboard.press('Escape');
	}

	await expect(async () => {
		const overlayCountAfterClose = await overlays.count();
		const visibleOverlaysAfterClose = await countVisibleOverlays();
		const targetClosed = !await fullscreenOverlay.isVisible().catch(() => false);
		expect(
			targetClosed
				|| overlayCountAfterClose < overlayCountBeforeClose
				|| visibleOverlaysAfterClose < visibleOverlaysBeforeClose
		).toBe(true);
	}).toPass({ timeout: 10000 });
}

module.exports = {
	EXPECTED_DT_HEADINGS,
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	dismissVisibleNotifications,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
};
