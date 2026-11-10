/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Design embroidery chat E2E (real inference, dev server only): the assistant
 * first creates a flat SVG graphic, then calls design.embroidery on it. The
 * result card shows the stitch preview with size and stitch count, the opened
 * view lists threads, numbers and five downloads, and the PES download hands
 * the browser a non-empty .pes file.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const fs = require('node:fs');

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');

const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const LOGO_PROMPT =
	'Create a simple flat three-colour logo of a fox head as an SVG graphic. No gradients, no text.';
const EMBROIDERY_PROMPT = 'Make this ready for our embroidery machine, 9 cm wide.';
const ANSWER_TIMEOUT = 420_000;
const FORMATS = ['dst', 'pes', 'exp', 'jef', 'vp3'];
const FINISHED_IMAGE =
	'[data-testid="embed-preview"][data-app-id="images"][data-status="finished"] [data-testid="image-generate-preview-image"]';

// contract-test: direct surface=gui.web assertions=design-embroidery.request.vector-source,design-embroidery.result.view-and-download,design-embroidery.result.complete-and-truthful
test('assistant turns a vector graphic into embroidery files that show and download', async ({ page }) => {
	test.setTimeout(1_200_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('design-embroidery-chat');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'design-embroidery-chat' });
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	await sendMessage(page, LOGO_PROMPT, log);
	await expect(page.locator(FINISHED_IMAGE).first()).toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
	await screenshot(page, 'vector-graphic-created');

	await sendMessage(page, EMBROIDERY_PROMPT, log);
	const card = page
		.getByTestId('embed-preview')
		.filter({ has: page.locator('[data-testid="design-embroidery-preview"][data-status="finished"]') })
		.first();
	await expect(card).toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });

	const image = card.getByTestId('design-embroidery-preview-image');
	await expect(image).toBeVisible();
	await expect
		.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
		.toBeGreaterThan(0);
	const numbers = card.getByTestId('design-embroidery-numbers');
	await expect(numbers).toContainText(/\d+\s*×\s*\d+\s*mm/);
	await expect(numbers).toContainText(/[\d.,]+\s*stitch/i);
	log(`card numbers: ${await numbers.textContent()}`);
	await card.scrollIntoViewIfNeeded();
	await screenshot(page, 'embroidery-card');

	await card.click();
	const fullscreen = page.getByTestId('design-embroidery-fullscreen');
	await expect(fullscreen).toBeVisible({ timeout: 30_000 });
	await expect(fullscreen).toHaveAttribute('data-status', 'finished');
	const fullImage = page.getByTestId('design-embroidery-image');
	await expect
		.poll(() => fullImage.evaluate((element: HTMLImageElement) => element.naturalWidth))
		.toBeGreaterThan(0);
	await expect(page.getByTestId('design-embroidery-size')).toContainText(/\d+\s*×\s*\d+\s*mm/);
	await expect(page.getByTestId('design-embroidery-stitch-count')).toContainText(/\d/);
	expect(await page.getByTestId('design-embroidery-thread').count()).toBeGreaterThan(0);
	for (const format of FORMATS) {
		const button = page.getByTestId(`design-embroidery-download-${format}`);
		await button.scrollIntoViewIfNeeded();
		await expect(button).toBeVisible();
		await expect(button).toBeEnabled();
	}
	await screenshot(page, 'embroidery-fullscreen');

	// The button fetches an owner-scoped signed URL and clicks a download anchor.
	const downloadPromise = page.waitForEvent('download', { timeout: 60_000 });
	await page.getByTestId('design-embroidery-download-pes').click();
	const download = await downloadPromise;
	expect(download.suggestedFilename().toLowerCase()).toMatch(/\.pes$/);
	const downloadedPath = await download.path();
	expect(downloadedPath, 'download finished and was saved').toBeTruthy();
	expect(fs.statSync(downloadedPath).size).toBeGreaterThan(0);
	await expect(page.getByTestId('design-embroidery-download-pes-error')).toHaveCount(0);
	await screenshot(page, 'embroidery-pes-downloaded');

	if (process.env.KEEP_EMBROIDERY_CHAT !== '1') {
		await page.keyboard.press('Escape');
		await deleteActiveChat(page, log);
	}
});
