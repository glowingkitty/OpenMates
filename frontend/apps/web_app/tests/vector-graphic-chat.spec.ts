/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Vector graphic chat E2E: the Auto model answers with a directly authored SVG,
 * which the web UI renders as an image and builds up while the answer streams.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const FIRST_PROMPT = "Create a simple flat logo for a coffee shop called 'Bean & Leaf' as an SVG.";
const FOLLOW_UP_PROMPT = 'Make the leaf orange and write the name in uppercase.';
const ANSWER_TIMEOUT = 180_000;

function decodeSvgDataUrl(src: string): string {
	const payload = src.slice(src.indexOf(',') + 1);
	if (/;base64,/.test(src.slice(0, src.indexOf(',') + 1))) {
		return Buffer.from(payload, 'base64').toString('utf-8');
	}
	return decodeURIComponent(payload);
}

async function waitForAnswerComplete(page: any, assistantIndex: number): Promise<void> {
	await expect(page.getByTestId('message-assistant').nth(assistantIndex)).toBeVisible({
		timeout: ANSWER_TIMEOUT
	});
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
}

async function finishedImageSrc(page: any, assistantIndex: number): Promise<string> {
	const message = page.getByTestId('message-assistant').nth(assistantIndex);
	const visual = message.getByTestId('svg-embed-visual').first();
	await expect(visual).toHaveAttribute('data-streaming', 'false', { timeout: ANSWER_TIMEOUT });
	const image = message.getByTestId('svg-embed-image').first();
	await expect(image).toBeVisible({ timeout: 30_000 });
	const src = await image.getAttribute('src');
	expect(src).toMatch(/^data:image\/svg\+xml/);
	return src as string;
}

// contract-test: direct surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming,ai-model-routing.use-case.specialised-automatic-models
test('vector graphic request renders an SVG image progressively and can be modified', async ({ page }) => {
	test.setTimeout(600_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('vector-graphic-chat');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'vector-graphic-chat' });
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	await sendMessage(page, FIRST_PROMPT, log);

	// Progressive rendering: poll for a streaming visual that already shows an image.
	let streamingObserved = false;
	let modelLabel = '';
	const timeline: string[] = [];
	const startedAt = Date.now();
	const streamingDeadline = Date.now() + ANSWER_TIMEOUT;
	while (Date.now() < streamingDeadline) {
		const streamingImage = page
			.locator('[data-testid="svg-embed-visual"][data-streaming="true"] [data-testid="svg-embed-image"]')
			.first();
		const probe = await page.evaluate(() => {
			const visual = document.querySelector('[data-testid="svg-embed-visual"]');
			const image = document.querySelector('[data-testid="svg-embed-image"]') as HTMLImageElement | null;
			return visual ? `${visual.getAttribute('data-streaming')}:${image ? image.src.length : 'pending'}` : 'none';
		});
		modelLabel =
			(await page.evaluate(
				() => document.querySelector('[data-testid="using-model"]')?.textContent ?? ''
			)) || modelLabel;
		if (timeline[timeline.length - 1]?.split('@')[0] !== probe) timeline.push(`${probe}@${Date.now() - startedAt}`);
		if (await streamingImage.isVisible().catch(() => false)) {
			if (!streamingObserved) await screenshot(page, 'svg-streaming');
			streamingObserved = true;
		}
		const finished = await page
			.locator('[data-testid="svg-embed-visual"][data-streaming="false"]')
			.count();
		if (finished > 0) break;
		await page.waitForTimeout(100);
	}
	log(`svg timeline: ${timeline.join(' ')}`);
	test.info().annotations.push({ type: 'svg-timeline', description: timeline.join(' ') });
	test.info().annotations.push({
		type: 'svg-streaming-frame-observed',
		description: String(streamingObserved)
	});
	expect(streamingObserved, 'streaming SVG frame was observed').toBe(true);
	// Once the picture is on screen it only grows: the card never falls back to a placeholder.
	const states = timeline.map((entry) => entry.split('@')[0]);
	const firstImage = states.findIndex((state) => /:\d+$/.test(state));
	const lastStreaming = states.map((state) => /^true:\d+$/.test(state)).lastIndexOf(true);
	const streamed = states.slice(firstImage, lastStreaming + 1);
	expect(streamed.filter((state) => !/^true:\d+$/.test(state))).toEqual([]);
	const sizes = streamed.map((state) => Number(state.split(':')[1]));
	expect(new Set(sizes).size, 'the streamed picture grew in several steps').toBeGreaterThan(2);

	await waitForAnswerComplete(page, 0);
	await expect(page.getByTestId('message-assistant')).toHaveCount(1);
	const firstSrc = await finishedImageSrc(page, 0);
	// The model label is only shown while the answer streams.
	expect(modelLabel).toContain('GPT-6.1 Sol');
	await screenshot(page, 'svg-created');

	await sendMessage(page, FOLLOW_UP_PROMPT, log);
	await waitForAnswerComplete(page, 1);
	await expect(page.getByTestId('message-assistant')).toHaveCount(2);
	const secondSrc = await finishedImageSrc(page, 1);
	expect(secondSrc).not.toBe(firstSrc);
	expect(decodeSvgDataUrl(secondSrc)).toContain('BEAN');
	await screenshot(page, 'svg-modified');

	await page.getByTestId('message-assistant').nth(1).getByTestId('result-preview-expand').first().click();
	const codeToggle = page.getByTestId('embed-preview-button');
	await expect(codeToggle).toBeVisible({ timeout: 15_000 });
	await expect(page.getByTestId('svg-embed-image')).toHaveCount(3);
	await screenshot(page, 'svg-fullscreen');
	await codeToggle.click();
	await expect(page.getByTestId('code-fullscreen-code')).toContainText('<svg', { timeout: 15_000 });
	await screenshot(page, 'svg-fullscreen-code');

	await page.keyboard.press('Escape');
	await deleteActiveChat(page, log);
});
