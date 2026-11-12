/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Image Enhance E2E (feature.embed-user-edits, web shell with the Rust core).
 *
 * A chat generates an image; the image fullscreen's Enhance button runs the
 * Enhance job through the shared Worker's client core, which stores the result
 * as the next version of the same image embed and writes the "Image enhanced"
 * chat event. The fullscreen shows the new version without a reload, a second
 * press cannot start another job, and the chat row stays after a reload.
 *
 * Real image generation and Enhance inference: runs only against the dev server
 * (no provider keys in isolated CI).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PROMPT = 'Generate a photo of a small red bicycle leaning against a white wall.';
const GENERATION_TIMEOUT_MS = 420_000;
const ENHANCE_TIMEOUT_MS = 420_000;
const IMAGE_CARD = '[data-message-id] [data-testid="embed-preview"][data-app-id="images"][data-status="finished"]';

async function openImageFullscreen(page: any): Promise<void> {
	const card = page.locator(IMAGE_CARD).last();
	await card.scrollIntoViewIfNeeded();
	// Result cards open from their Details button; the picture itself is not a click target.
	await card.getByTestId('result-preview-expand').click();
	await expect(page.locator('.image-wrapper[data-embed-version] img').first()).toBeVisible({ timeout: 60_000 });
}

// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button,embed-user-edits.edit.next-version,embed-user-edits.event.chat-notice
test('Enhance saves the enhanced picture as the next version and notes it in the chat', async ({ page }) => {
	test.setTimeout(1_200_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('image-enhance');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'image-enhance' });
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(page, PROMPT, log);
	await expect(page.locator(`${IMAGE_CARD} [data-testid="image-generate-preview-image"]`).last())
		.toBeVisible({ timeout: GENERATION_TIMEOUT_MS });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: GENERATION_TIMEOUT_MS });
	const embedId = await page.locator(IMAGE_CARD).last().getAttribute('data-embed-id');
	expect(embedId, 'the generated image card names its embed').toBeTruthy();
	await screenshot(page, 'image-generated');

	await openImageFullscreen(page);
	const wrapper = page.locator('.image-wrapper[data-embed-version]').first();
	const before = Number(await wrapper.getAttribute('data-embed-version'));
	const beforeSrc = await wrapper.locator('img').first().getAttribute('src');
	expect(before).toBeGreaterThanOrEqual(1);

	// embed-user-edits.enhance.button: one press runs the job; while it runs the button cannot start another.
	const enhance = page.getByTestId('embed-enhance-button');
	await expect(enhance).toBeVisible({ timeout: 30_000 });
	await expect(enhance).toBeEnabled();
	await enhance.click();
	await expect(page.getByTestId('embed-enhance-progress')).toBeVisible({ timeout: 30_000 });
	await expect(enhance).toBeDisabled();
	await screenshot(page, 'enhance-running');

	// embed-user-edits.edit.next-version: the same embed shows the next version without a reload.
	const next = before + 1;
	await expect(page.locator(`.image-wrapper[data-embed-version="${next}"] img`)).toBeVisible({ timeout: ENHANCE_TIMEOUT_MS });
	await expect(page.getByTestId('embed-enhance-progress')).toHaveCount(0);
	const afterSrc = await page.locator(`.image-wrapper[data-embed-version="${next}"] img`).first().getAttribute('src');
	expect(afterSrc, 'the enhanced picture differs from the original').not.toBe(beforeSrc);
	await expect(page.getByTestId('image-generate-version-badge').first()).toBeVisible();
	await screenshot(page, 'enhance-saved');

	// embed-user-edits.event.chat-notice: the chat shows "Image enhanced" as a quiet row, not a bubble.
	await page.keyboard.press('Escape');
	const notice = page.locator('[data-testid="embed-updated-event"][data-action="enhance"]').last();
	await expect(notice).toBeVisible({ timeout: 60_000 });
	await expect(notice).toContainText(String(next));
	await expect(page.locator('[data-testid="message-system"]').filter({ hasText: '"embed_updated"' })).toHaveCount(0);
	await screenshot(page, 'enhance-chat-notice');

	// Stored: after a reload the row and the new version are still there, on the same embed.
	await page.reload();
	await expect(page.locator('[data-testid="embed-updated-event"][data-action="enhance"]').last())
		.toBeVisible({ timeout: 90_000 });
	await openImageFullscreen(page);
	await expect(page.locator(`.image-wrapper[data-embed-version="${next}"] img`)).toBeVisible({ timeout: 60_000 });
	expect(await page.locator(IMAGE_CARD).last().getAttribute('data-embed-id')).toBe(embedId);
	await screenshot(page, 'enhance-after-reload');

	await page.keyboard.press('Escape');
	if (process.env.KEEP_IMAGE_ENHANCE_CHAT !== '1') await deleteActiveChat(page, log);
});
