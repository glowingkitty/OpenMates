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
	/** `<embed id>@v<version>` of finished image cards whose picture is loaded (off-screen cards unload theirs). */
	finishedIds: string[];
	model: string;
	/** The request shown on the card before a picture exists. */
	requestPrompt: string;
	requestModel: string;
	requestInputImages: number;
}

async function probeDrawing(page: any): Promise<DraftProbe> {
	return page.evaluate((finishedSelector: string) => {
		const draft = document.querySelector('[data-testid="image-generate-svg-draft"]');
		const request = document.querySelector('[data-testid="image-generate-request"]');
		const image = draft?.querySelector('[data-testid="svg-embed-image"]') as HTMLImageElement | null;
		return {
			stage: draft ? (draft.getAttribute('data-stage') ?? 'drawing') : request ? 'request' : 'none',
			requestPrompt: request?.querySelector('[data-testid="image-generate-request-prompt"]')?.textContent?.trim() ?? '',
			requestModel: request?.querySelector('[data-testid="image-generate-request-model"]')?.textContent?.trim() ?? '',
			requestInputImages: request?.querySelectorAll('[data-testid="image-generate-request-input"] img').length ?? 0,
			size: image ? image.src.length : 0,
			finishedIds: Array.from(document.querySelectorAll(finishedSelector)).map((image) => {
				const embedId = image.closest('[data-embed-id]')?.getAttribute('data-embed-id') ?? '';
				return embedId ? `${embedId}@v${image.getAttribute('data-embed-version') ?? '1'}` : '';
			}),
			model: document.querySelector('[data-testid="using-model"]')?.textContent ?? ''
		};
	}, FINISHED_IMAGE);
}

interface MessagePicture {
	messageId: string;
	embedId: string;
	version: string;
	src: string;
}

/** The finished picture each chat message shows, in chat order (one per message). */
async function messagePictures(page: any): Promise<MessagePicture[]> {
	return page.evaluate((finishedSelector: string) => {
		const pictures: { messageId: string; embedId: string; version: string; src: string }[] = [];
		for (const message of Array.from(document.querySelectorAll('[data-message-id]'))) {
			const image = message.querySelector(finishedSelector) as HTMLImageElement | null;
			if (!image) continue;
			pictures.push({
				messageId: message.getAttribute('data-message-id') ?? '',
				embedId: image.closest('[data-embed-id]')?.getAttribute('data-embed-id') ?? '',
				version: image.getAttribute('data-embed-version') ?? '',
				src: image.getAttribute('src') ?? ''
			});
		}
		return pictures;
	}, FINISHED_IMAGE);
}

/** Scroll through the chat so every message's card loads its picture, then read them. */
async function readAllMessagePictures(page: any, expected: number): Promise<MessagePicture[]> {
	const deadline = Date.now() + 60_000;
	let pictures: MessagePicture[] = [];
	while (Date.now() < deadline) {
		for (const card of await page.locator('[data-message-id] [data-testid="embed-preview"][data-app-id="images"]').all()) {
			await card.scrollIntoViewIfNeeded();
		}
		pictures = await messagePictures(page);
		if (pictures.length >= expected && pictures.every((picture) => picture.src)) break;
		await page.waitForTimeout(500);
	}
	return pictures;
}

/** One image embed for the whole chat; message N shows version N with its own picture. */
function expectOneEmbedVersionPerMessage(pictures: MessagePicture[], label: string): void {
	expect(pictures.map((picture) => picture.version), `${label}: each message shows its own version`).toEqual(['1', '2', '3']);
	expect(new Set(pictures.map((picture) => picture.embedId)).size, `${label}: one image embed for the chat`).toBe(1);
	expect(new Set(pictures.map((picture) => picture.src)).size, `${label}: the three messages show different pictures`).toBe(3);
}

/** Follow one drawing until `finishedTarget` different finished image versions have been shown. */
async function followDrawing(
	page: any, seen: Set<string>, finishedTarget: number,
	onFirstProgress: () => Promise<void>, onFirstPicture: () => Promise<void>, wantsInputImage = false
) {
	const timeline: string[] = [];
	const sizes = new Set<number>();
	const stages = new Set<string>();
	let model = '';
	const request = { prompt: '', model: '', inputImages: 0, shownBeforePicture: false, captured: false };
	let pictureCaptured = false;
	const startedAt = Date.now();
	let followedAt = 0;
	while (Date.now() - startedAt < ANSWER_TIMEOUT) {
		// A reader follows the answer: cards below the fold do not load their picture.
		if (Date.now() - followedAt > 1_000) {
			followedAt = Date.now();
			await page.locator('[data-message-id] [data-testid="embed-preview"][data-app-id="images"]').last()
				.scrollIntoViewIfNeeded({ timeout: 2_000 }).catch(() => undefined);
		}
		const probe = await probeDrawing(page);
		model = probe.model || model;
		if (probe.stage !== 'none') {
			if (probe.stage === 'request' && sizes.size === 0) request.shownBeforePicture = true;
			stages.add(probe.stage);
		}
		if (probe.stage === 'request') {
			request.prompt = probe.requestPrompt || request.prompt;
			request.model = probe.requestModel || request.model;
			request.inputImages = Math.max(request.inputImages, probe.requestInputImages);
			// Capture the request once it is complete (a modification also shows its input image).
			if (!request.captured && request.prompt && (!wantsInputImage || request.inputImages > 0)) {
				request.captured = true;
				await onFirstProgress();
			}
		}
		if (probe.size > 0 && sizes.size >= 2 && !pictureCaptured) {
			pictureCaptured = true;
			await onFirstPicture();
		}
		if (probe.size > 0) sizes.add(probe.size);
		for (const embedId of probe.finishedIds) if (embedId) seen.add(embedId);
		const state = `${probe.stage}:${probe.size}:${seen.size}`;
		if (timeline[timeline.length - 1]?.split('@')[0] !== state) timeline.push(`${state}@${Date.now() - startedAt}`);
		if (seen.size >= finishedTarget) break;
		await page.waitForTimeout(100);
	}
	return { timeline, sizes, stages, model, request };
}

/** Progress was visible: a hand-written SVG grew in steps, or a generator script showed its stage. */
function expectVisibleProgress(run: { sizes: Set<number>; stages: Set<string> }, label: string): void {
	const grewInSteps = run.sizes.size > 2;
	const scripted = run.stages.has('scripting');
	expect(grewInSteps || scripted, `${label}: progress was shown while the graphic was made`).toBe(true);
}

// contract-test: direct surface=gui.web assertions=images-generate.vector.progressive-drafts,images-generate.vector.skill-authors-svg,images-generate.vector.references-vector-and-pixel
// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
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
	const seen = new Set<string>();
	const created = await followDrawing(
		page, seen, 1, () => screenshot(page, 'svg-request'), () => screenshot(page, 'svg-drawing')
	);
	log(`create request: ${JSON.stringify(created.request)}`);
	log(`create timeline: ${created.timeline.join(' ')}`);
	test.info().annotations.push({ type: 'svg-create-timeline', description: created.timeline.join(' ') });
	test.info().annotations.push({ type: 'chat-model', description: created.model });

	expectVisibleProgress(created, 'creation');
	// Before any picture exists the card shows what was asked for and which model draws it.
	expect(created.request.shownBeforePicture, 'the request was shown before the first picture').toBe(true);
	expect(created.request.prompt.length, 'the card showed the prompt').toBeGreaterThan(10);
	expect(created.request.model, 'the card named the drawing model').toMatch(/sol/i);
	expect(created.request.inputImages, 'a new graphic has no input image').toBe(0);
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
		const before = new Set(seen);
		const modified = await followDrawing(
			page, seen, target,
			() => screenshot(page, `svg-modify-request-${index + 1}`),
			() => screenshot(page, `svg-modifying-${index + 1}`), true
		);
		log(`modify ${index + 1} timeline: ${modified.timeline.join(' ')}`);
		log(`modify ${index + 1} request: ${JSON.stringify(modified.request)}`);
		test.info().annotations.push({
			type: `svg-modify-${index + 1}-timeline`,
			description: modified.timeline.join(' ')
		});
		expect(modified.stages.size, `follow-up ${index + 1} showed progress`).toBeGreaterThan(0);
		// A modification shows the graphic it starts from next to the change request.
		expect(modified.request.prompt.length, `follow-up ${index + 1} showed its prompt`).toBeGreaterThan(5);
		expect(modified.request.inputImages, `follow-up ${index + 1} showed its input image`).toBeGreaterThan(0);

		// A new version of the same image was made; the earlier message keeps its own picture.
		expect(seen.size, `follow-up ${index + 1} produced a new version`).toBe(target);
		const newVersion = [...seen].find((entry) => !before.has(entry)) ?? '';
		const [newId, versionLabel] = newVersion.split('@v');
		expect(versionLabel, `follow-up ${index + 1} made version ${target}`).toBe(String(target));
		await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
		const newImage = page
			.locator(`[data-embed-id="${newId}"] [data-testid="image-generate-preview-image"][data-embed-version="${target}"]`)
			.first();
		await newImage.scrollIntoViewIfNeeded();
		await expect(newImage).toBeVisible({ timeout: ANSWER_TIMEOUT });
		const src = await newImage.getAttribute('src');
		expect(src).toBeTruthy();
		expect(sources).not.toContain(src);
		sources.push(src);
		await expect(page.getByTestId('svg-embed-visual')).toHaveCount(0);
		await screenshot(page, `svg-modified-${index + 1}`);
	}

	// One image embed for the whole chat; each message shows the version it made.
	const live = await readAllMessagePictures(page, 3);
	log(`message pictures: ${JSON.stringify(live.map(({ messageId, version }) => ({ messageId, version })))}`);
	expectOneEmbedVersionPerMessage(live, 'live');
	await expect(page.getByTestId('image-generate-version-badge').first()).toBeVisible();

	// The same after a reload: the versions come from the stored rows and the pins.
	// The last answer is stored a moment after its stream ends; this check is about
	// stored versions, not about reloading in the middle of that save.
	await page.waitForTimeout(15_000);
	await page.reload();
	const reloaded = await readAllMessagePictures(page, 3);
	expectOneEmbedVersionPerMessage(reloaded, 'after reload');
	expect(reloaded.map((picture) => picture.messageId)).toEqual(live.map((picture) => picture.messageId));
	await screenshot(page, 'svg-versions-after-reload');

	// Fullscreen from the last message opens at its version, with a timeline of all three.
	const lastImage = page.locator(
		`[data-message-id="${reloaded[2].messageId}"] [data-testid="image-generate-preview-image"][data-embed-version="3"]`
	).first();
	await lastImage.scrollIntoViewIfNeeded();
	await lastImage.click();
	const timeline = page.getByTestId('embed-version-timeline');
	await expect(timeline).toBeVisible({ timeout: 30_000 });
	for (const version of [1, 2, 3]) await expect(timeline.getByTestId(`version-dot-${version}`)).toBeVisible();
	await expect(page.locator('.image-wrapper[data-embed-version="3"]')).toBeVisible({ timeout: 30_000 });
	// Selecting version 1 shows the first picture.
	await timeline.getByTestId('version-dot-1').click();
	await expect(page.locator('.image-wrapper[data-embed-version="1"] img')).toBeVisible({ timeout: 30_000 });
	await screenshot(page, 'svg-versions-fullscreen');

	if (process.env.KEEP_VECTOR_CHAT !== '1') await deleteActiveChat(page, log);
});
