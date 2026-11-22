/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the raw Playwright video and attached phone screenshots cover each checkpoint)
/**
 * Upload an image in a new chat and ask for an SVG based on it (real-inference proof, TASK-2115).
 *
 * Runs in the `real_inference` CI group (isolated per-run stack, fresh CI account) and
 * still manually against dev through scripts/image_upload_svg_web_real_test.py, on a
 * phone viewport, without mocks. The model is @Gemini-3.8-Flash. Before the fix
 * the turn ended with an AI error: images.view put the photo bytes into the turn
 * transcript, the generate pause could not store it ("too large to suspend"),
 * and the generate card kept spinning because its error state was never sealed.
 *   1. @Gemini-3.8-Flash gets an uploaded photo and "Create an SVG file based on this image".
 *   2. The turn completes: no card stays on "processing", no message error banner.
 *   3. The View card shows the uploaded image; cards are in call order (View, then Generate).
 *   4. The Generate card uses the AI sparkle as its skill icon and ends finished.
 * The chat is deleted afterwards.
 */
import type { Page } from '@playwright/test';

const path = require('path');
const fs = require('fs');
const { expect, test } = require('./helpers/cookie-audit');
const {
	deleteActiveChat,
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const { requireRealInference } = require('./helpers/real-inference-guard');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const IMAGE_FIXTURE = path.join(__dirname, 'fixtures', 'golden_gate_bridge.jpg');
const PROMPT = ' Create an SVG file based on this image.';
const TURN_TIMEOUT_MS = 600_000;

const viewCard = (page: Page) =>
	page.locator('[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="images"][data-skill-id="view"]');
const generateCard = (page: Page) =>
	page.locator('[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="images"][data-skill-id="generate"]');

async function attachImage(page: Page, log: any): Promise<void> {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10_000 });
	// A unique suffix avoids reusing a stale upload row of the shared fixture hash.
	const buffer = Buffer.concat([fs.readFileSync(IMAGE_FIXTURE), Buffer.from(`\nopenmates-e2e-${Date.now()}`)]);
	await fileInput.setInputFiles({ name: 'image.jpg', mimeType: 'image/jpeg', buffer });
	const editorPreview = page.getByTestId('message-editor')
		.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="view"]');
	await expect(editorPreview.first()).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
	await expect(editorPreview.first()).not.toContainText(/Uploading/i, { timeout: 120_000 });
	log('Uploaded the photo.');
}

/** Pick the model first: a mention typed after an attachment lands in front of the embed. */
async function mentionGemini(page: Page): Promise<void> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
}

async function askForSvg(page: Page, log: any): Promise<void> {
	const editor = page.getByTestId('message-editor');
	// Phone layout: make sure the chat sidebar overlay is closed before focusing the composer.
	await setChatSidebarOpen(page, false, log);
	const editable = editor.locator('[contenteditable="true"]');
	// The phone composer can collapse to its one-line placeholder; tap its top-left corner
	// (never the image) to expand it before focusing.
	await focusMessageEditor(editor).catch(async () => {
		await editor.click({ position: { x: 12, y: 8 } });
		await focusMessageEditor(editor);
	});
	// Place the caret after the image embed (same steps as image-model-inference-real.spec.ts).
	await editable.press('ControlOrMeta+End');
	await editable.press('ArrowRight');
	await editable.press('Enter');
	await page.keyboard.insertText(PROMPT.trim());
	await expect(editable).toContainText(PROMPT.trim());
	await page.keyboard.press('Escape');
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
	// The sent message shows the photo card, never the raw embed block.
	const sent = page.getByTestId('message-user').last();
	await expect(sent.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="view"]').first()).toBeVisible({ timeout: 30_000 });
	await expect(sent).not.toContainText('"embed_id"');
	log('Asked @Gemini-3.8-Flash for an SVG based on the photo.');
}

/** The turn is over when the stop button and typing indicator stay hidden for 5 s. */
async function waitForIdle(page: Page): Promise<void> {
	const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
	let idleSince = 0;
	await expect.poll(async () => {
		if ((await busy.count()) > 0) {
			idleSince = 0;
			return false;
		}
		idleSince ||= Date.now();
		return Date.now() - idleSince >= 5_000;
	}, { timeout: TURN_TIMEOUT_MS, intervals: [1_000] }).toBe(true);
}

// contract-test: direct surface=gui.web assertions=app-skills.assistant.same-turn-completion,chats.rendering.skill-card-call-order
test('an uploaded photo plus "make an SVG of it" completes on a phone with View and Generate cards in call order', async ({ page }: { page: Page }, testInfo: any) => {
	test.setTimeout(900_000);
	requireRealInference('image-upload-svg', BASE_URL);
	if (!getTestAccount().email) throw new Error('Real-inference run requires a provisioned test account.');
	await page.setViewportSize({ width: 390, height: 844 });
	const log = createSignupLogger('IMAGE_UPLOAD_SVG');
	const screenshot = createStepScreenshotter(log);
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page, log, screenshot);
	await setChatSidebarOpen(page, false, log);
	await startNewChat(page, log);

	try {
		await mentionGemini(page);
		await attachImage(page, log);
		await askForSvg(page, log);

		// The generate card appears and is visible without scrolling the card row.
		await expect(generateCard(page).first()).toBeVisible({ timeout: 240_000 });
		// Bring the card row into view vertically only (the chat keeps the reply start in view);
		// the row itself must already show the running card without horizontal scrolling.
		const row = generateCard(page).first().locator('xpath=ancestor::*[@data-testid="app-skill-embed-group"][1]');
		await row.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
		await expect(generateCard(page).first()).toBeInViewport({ ratio: 0.9, timeout: 30_000 });
		await expect(generateCard(page).first().locator('[data-skill-icon]').first()).toHaveAttribute('data-skill-icon', 'ai');
		await testInfo.attach('01-generate-card-running', { body: await page.screenshot(), contentType: 'image/png' });
		// The input photo thumbnail decrypts shortly after the card appears; the streaming draft
		// later replaces it, so capture it when it loads (a draft that arrives first wins the race).
		const inputThumb = generateCard(page).first().getByTestId('image-generate-request-input').locator('img').first();
		if (await inputThumb.waitFor({ state: 'visible', timeout: 30_000 }).then(() => true, () => false)) {
			await testInfo.attach('01b-input-thumbnail', { body: await page.screenshot(), contentType: 'image/png' });
			log('The input photo thumbnail is shown in the generate card.');
		} else {
			log('The input photo thumbnail did not load before the draft replaced it.');
		}
		const draft = generateCard(page).first().getByTestId('image-generate-svg-draft');
		if (await draft.waitFor({ state: 'visible', timeout: 120_000 }).then(() => true, () => false)) {
			await testInfo.attach('02-svg-streaming', { body: await page.screenshot(), contentType: 'image/png' });
			log('The partial SVG streamed into the generate card.');
		} else {
			log('No partial SVG frame was visible before the result (the result may have arrived first).');
		}

		await waitForIdle(page);
		await expect(generateCard(page).first()).toHaveAttribute('data-status', 'finished', { timeout: 60_000 });
		await expect(page.locator('[data-testid="embed-preview"][data-status="processing"]')).toHaveCount(0);
		await expect(page.getByTestId('embed-error-banner')).toHaveCount(0);

		// The model decides whether it calls images.view (the photo is already in the prompt).
		// When it does, the View card shows the uploaded photo and comes before the Generate card.
		const order = await page.locator('[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="images"]')
			.evaluateAll(cards => cards.map(card => card.getAttribute('data-skill-id')));
		log(`Assistant image cards in DOM order: ${order.join(', ')}`);
		if (order.includes('view')) {
			const view = viewCard(page).first();
			await expect(view).toHaveAttribute('data-status', 'finished');
			await expect(view.locator('img').first()).toBeVisible({ timeout: 60_000 });
			expect(order.indexOf('view')).toBeLessThan(order.indexOf('generate'));
			await view.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
			await testInfo.attach('03-view-card-with-photo', { body: await page.screenshot(), contentType: 'image/png' });
		}
		await generateCard(page).first().evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
		await testInfo.attach('04-generate-card-finished', { body: await page.screenshot(), contentType: 'image/png' });
	} finally {
		await deleteActiveChat(page, log, screenshot);
	}
});
