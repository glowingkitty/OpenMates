/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Vector graphic chat E2E: the ordinary Auto chat model calls images-generate
 * with SVG output; the skill's vector author draws the graphic, the card shows
 * the drawing building up, and follow-ups change the generated graphic.
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

const FIRST_PROMPT =
	'Create an embroiderable pattern of a fire-inspired tail (vertical) as an SVG. It will be embroidered as is, so no gradients.';
const FOLLOW_UPS = [
	'Make the tail slimmer and add one more flame tip at the top.',
	'Now use only two colours: red and yellow.'
];
const ANSWER_TIMEOUT = 420_000;
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
		const status = document.querySelector('[data-testid="image-generate-draft-status"]');
		const image = draft?.querySelector('[data-testid="svg-embed-image"]') as HTMLImageElement | null;
		return {
			stage: (draft ?? status)?.getAttribute('data-stage') ?? 'none',
			size: image ? image.src.length : 0,
			finished: document.querySelectorAll(finishedSelector).length,
			model: document.querySelector('[data-testid="using-model"]')?.textContent ?? ''
		};
	}, FINISHED_IMAGE);
}

/** Follow one drawing until `finishedTarget` finished vector images are on screen. */
async function followDrawing(page: any, finishedTarget: number, onFirstProgress: () => Promise<void>) {
	const timeline: string[] = [];
	const sizes = new Set<number>();
	const stages = new Set<string>();
	let model = '';
	const startedAt = Date.now();
	while (Date.now() - startedAt < ANSWER_TIMEOUT) {
		const probe = await probeDrawing(page);
		model = probe.model || model;
		if (probe.stage !== 'none') {
			if (stages.size === 0) await onFirstProgress();
			stages.add(probe.stage);
		}
		if (probe.size > 0) sizes.add(probe.size);
		const state = `${probe.stage}:${probe.size}:${probe.finished}`;
		if (timeline[timeline.length - 1]?.split('@')[0] !== state) timeline.push(`${state}@${Date.now() - startedAt}`);
		if (probe.finished >= finishedTarget) break;
		await page.waitForTimeout(100);
	}
	return { timeline, sizes, stages, model };
}

/** Progress was visible: a hand-written SVG grew in steps, or a generator script showed its stage. */
function expectVisibleProgress(run: { sizes: Set<number>; stages: Set<string> }, label: string): void {
	const grewInSteps = run.sizes.size > 2;
	const scripted = run.stages.has('scripting');
	expect(grewInSteps || scripted, `${label}: progress was shown while the graphic was made`).toBe(true);
}

// contract-test: direct surface=gui.web assertions=images-generate.vector.progressive-drafts,images-generate.vector.skill-authors-svg,images-generate.vector.references-vector-and-pixel
test('embroidery vector graphic is made by the images skill, shows progress, and follow-ups modify it', async ({ page }) => {
	test.setTimeout(1_500_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('vector-graphic-chat');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'vector-graphic-chat' });
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	await sendMessage(page, FIRST_PROMPT, log);
	const created = await followDrawing(page, 1, () => screenshot(page, 'svg-in-progress'));
	log(`create timeline: ${created.timeline.join(' ')}`);
	test.info().annotations.push({ type: 'svg-create-timeline', description: created.timeline.join(' ') });
	test.info().annotations.push({ type: 'chat-model', description: created.model });

	expectVisibleProgress(created, 'creation');
	// The chat answer comes from the ordinary routed model, not the vector author model.
	expect(created.model).not.toContain('GPT-6.1 Sol');

	await expect(page.locator(FINISHED_IMAGE).first()).toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
	await expect(page.getByTestId('image-generate-svg-draft')).toHaveCount(0);
	// The assistant did not write the SVG as a code block.
	await expect(page.getByTestId('svg-embed-visual')).toHaveCount(0);
	const sources = [await page.locator(FINISHED_IMAGE).first().getAttribute('src')];
	await screenshot(page, 'svg-created');

	for (const [index, prompt] of FOLLOW_UPS.entries()) {
		const target = index + 2;
		await sendMessage(page, prompt, log);
		const modified = await followDrawing(page, target, () => screenshot(page, `svg-modifying-${index + 1}`));
		log(`modify ${index + 1} timeline: ${modified.timeline.join(' ')}`);
		test.info().annotations.push({
			type: `svg-modify-${index + 1}-timeline`,
			description: modified.timeline.join(' ')
		});
		expect(modified.stages.size, `follow-up ${index + 1} showed progress`).toBeGreaterThan(0);

		await expect(page.locator(FINISHED_IMAGE)).toHaveCount(target, { timeout: ANSWER_TIMEOUT });
		await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
		const src = await page.locator(FINISHED_IMAGE).nth(target - 1).getAttribute('src');
		expect(src).toBeTruthy();
		expect(sources).not.toContain(src);
		sources.push(src);
		await page.locator(FINISHED_IMAGE).nth(target - 1).scrollIntoViewIfNeeded();
		await screenshot(page, `svg-modified-${index + 1}`);
	}

	if (process.env.KEEP_VECTOR_CHAT !== '1') await deleteActiveChat(page, log);
});
