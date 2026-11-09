/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Vector graphic chat E2E: the ordinary Auto chat model calls images-generate
 * with SVG output; the skill's vector author draws the graphic, the card shows
 * the drawing building up, and a follow-up changes the generated graphic.
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
const ANSWER_TIMEOUT = 300_000;
const FINISHED_IMAGE =
	'[data-testid="embed-preview"][data-app-id="images"][data-status="finished"] [data-testid="image-generate-preview-image"]';

interface DraftProbe {
	stage: string;
	size: number;
	finished: number;
	model: string;
}

async function probeDrawing(page: any): Promise<DraftProbe> {
	return page.evaluate((finishedSelector: string) => {
		const draft = document.querySelector('[data-testid="image-generate-svg-draft"]');
		const image = draft?.querySelector('[data-testid="svg-embed-image"]') as HTMLImageElement | null;
		return {
			stage: draft ? (draft.getAttribute('data-stage') ?? 'unknown') : 'none',
			size: image ? image.src.length : 0,
			finished: document.querySelectorAll(finishedSelector).length,
			model: document.querySelector('[data-testid="using-model"]')?.textContent ?? ''
		};
	}, FINISHED_IMAGE);
}

/** Follow one drawing until `finishedTarget` finished vector images are on screen. */
async function followDrawing(page: any, finishedTarget: number, onFirstDraft: () => Promise<void>) {
	const timeline: string[] = [];
	const sizes = new Set<number>();
	const stages = new Set<string>();
	let model = '';
	const startedAt = Date.now();
	while (Date.now() - startedAt < ANSWER_TIMEOUT) {
		const probe = await probeDrawing(page);
		model = probe.model || model;
		if (probe.size > 0) {
			if (sizes.size === 0) await onFirstDraft();
			sizes.add(probe.size);
			stages.add(probe.stage);
		}
		const state = `${probe.stage}:${probe.size}:${probe.finished}`;
		if (timeline[timeline.length - 1]?.split('@')[0] !== state) timeline.push(`${state}@${Date.now() - startedAt}`);
		if (probe.finished >= finishedTarget) break;
		await page.waitForTimeout(100);
	}
	return { timeline, sizes, stages, model };
}

// contract-test: direct surface=gui.web assertions=images-generate.vector.progressive-drafts,images-generate.vector.skill-authors-svg,images-generate.vector.references-vector-and-pixel
test('vector graphic is drawn by the images skill, builds up while drawn, and can be modified', async ({ page }) => {
	test.setTimeout(900_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('vector-graphic-chat');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'vector-graphic-chat' });
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	await sendMessage(page, FIRST_PROMPT, log);
	const created = await followDrawing(page, 1, () => screenshot(page, 'svg-drawing'));
	log(`create timeline: ${created.timeline.join(' ')}`);
	test.info().annotations.push({ type: 'svg-create-timeline', description: created.timeline.join(' ') });
	test.info().annotations.push({ type: 'chat-model', description: created.model });

	// The picture builds up in several steps instead of jumping from empty to finished.
	expect(created.sizes.size, 'the drawing grew in several visible steps').toBeGreaterThan(2);
	expect([...created.stages]).toContain('drawing');
	// The chat answer comes from the ordinary routed model, not the vector author model.
	expect(created.model).not.toContain('GPT-6.1 Sol');

	await expect(page.locator(FINISHED_IMAGE).first()).toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('image-generate-svg-draft')).toHaveCount(0);
	// The assistant did not write the SVG as a code block.
	await expect(page.getByTestId('svg-embed-visual')).toHaveCount(0);
	const firstSrc = await page.locator(FINISHED_IMAGE).first().getAttribute('src');
	await screenshot(page, 'svg-created');

	await sendMessage(page, FOLLOW_UP_PROMPT, log);
	const modified = await followDrawing(page, 2, () => screenshot(page, 'svg-modifying'));
	log(`modify timeline: ${modified.timeline.join(' ')}`);
	test.info().annotations.push({ type: 'svg-modify-timeline', description: modified.timeline.join(' ') });
	expect(modified.sizes.size, 'the modified drawing was shown while it was written').toBeGreaterThan(0);

	await expect(page.locator(FINISHED_IMAGE)).toHaveCount(2, { timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
	const secondSrc = await page.locator(FINISHED_IMAGE).nth(1).getAttribute('src');
	expect(secondSrc).toBeTruthy();
	expect(secondSrc).not.toBe(firstSrc);
	await page.locator(FINISHED_IMAGE).nth(1).scrollIntoViewIfNeeded();
	await screenshot(page, 'svg-modified');

	await deleteActiveChat(page, log);
});
