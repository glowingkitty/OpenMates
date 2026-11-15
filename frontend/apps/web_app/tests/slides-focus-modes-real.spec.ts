/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)

/**
 * Slides focus modes (real inference, dev server only): "Design a template" and
 * "Plan a presentation" run with Gemini 3.8 Flash and the real Jev phase gates.
 * Replies are scripted short answers sent in a bounded loop until the expected
 * element (template cards, deck embed) appears.
 *
 * Run through scripts/slides_focus_web_real_test.py (personal dev test account,
 * leases, installed Chromium, output outside the repository).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	focusMessageEditor
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen, closeFullscreen, showCarouselCard } = require('./helpers/embed-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;
const ANSWER_TIMEOUT = 420_000;
const MAX_TURNS = 6;
const FINISHED = '[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]';

const DESIGN_BRIEF =
	'@focus:slides:design_template Design a slide template for our school robotics club, our colours are dark blue and orange, friendly but clean';
const DESIGN_REPLIES = [
	'Mostly parents and students, around 20 slides at a time. No logo for now.',
	'Yes, that summary is right, please show me the designs.',
	'Yes, looks good. Please go ahead and show three designs.',
	'Any of the styles is fine, please just show the three designs now.',
	'Yes, please continue.'
];
const PLAN_BRIEF =
	"@focus:slides:plan_presentation I need slides for my hackathon project but I don't know how to start. It's an app that helps students find study partners, 5 minute pitch tomorrow";
const PLAN_REPLIES = [
	'The goal is to win the jury for a pilot at two schools. The audience is mostly engineers and teachers.',
	'Yes, that summary is right.',
	'Yes, looks good.',
	'Yes, that outline is right.',
	'Please use the Bold pitch design.',
	'Yes, please continue.'
];

const assistantCount = (page: any): Promise<number> => page.getByTestId('message-assistant').count();

/**
 * Insert the Gemini 3.8 Flash mention through the dropdown, then send the text after it.
 * Returns the assistant message count before the send, for waitForReply.
 */
async function sendWithGemini(page: any, prompt: string, log: any, screenshot: any, label: string): Promise<number> {
	const before = await assistantCount(page);
	const editor = page.getByTestId('message-field').last().getByTestId('message-editor');
	await expect(editor).toBeVisible();
	// Like a person, wait until the composer accepts a new message: the previous send can hold
	// the send guard (aria-busy) after its reply finished. The wait is logged so the delay stays visible.
	const busySince = Date.now();
	const sendButton = page.getByTestId('message-field').last().getByTestId('composer-send-button');
	await expect.poll(async () => (await sendButton.count()) > 0 && (await sendButton.last().getAttribute('aria-busy')) === 'true',
		{ timeout: 180_000 }).toBe(false);
	const busyMs = Date.now() - busySince;
	if (busyMs > 2000) log(`composer send stayed busy for ${Math.round(busyMs / 1000)}s before "${label}"`);
	await focusMessageEditor(editor);
	await page.keyboard.insertText(`@${MODEL_QUERY}`);
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown).toBeVisible({ timeout: 10_000 });
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
		.toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).not.toBeVisible({ timeout: 3000 });
	await sendMessage(page, ` ${prompt}`, log, screenshot, label, { preserveExistingContent: true });
	return before;
}

/**
 * Wait until the reply to the last send is finished: a new assistant message exists (more than
 * `before`), no typing indicator, and its model label is shown (rendered only once the response
 * is no longer active, ChatMessage.svelte). Without the count, the previous reply's label passes
 * while the new answer is still streaming and the next scripted answer hits a busy composer.
 */
async function waitForReply(page: any, log: any, before: number) {
	await expect.poll(() => assistantCount(page), { timeout: ANSWER_TIMEOUT }).toBeGreaterThan(before);
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
	const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
	await expect(generatedBy).toBeVisible({ timeout: 120_000 });
	await expect(generatedBy).toContainText(MODEL_NAME);
	log(`reply generated by: ${(await generatedBy.textContent())?.trim()}`);
}

/**
 * After each finished reply, return once `done` is true; otherwise send the next scripted answer.
 * Fails clearly when the expected element is still missing after MAX_TURNS replies.
 */
async function answerUntil(page: any, log: any, screenshot: any, phase: string, replies: string[],
	before: number, done: () => Promise<boolean>) {
	for (let turn = 0; turn < MAX_TURNS; turn++) {
		await waitForReply(page, log, before);
		if (await done().catch(() => false)) return;
		if (turn >= replies.length) break;
		await screenshot(page, `${phase}-turn-${turn + 1}`);
		before = await sendWithGemini(page, replies[turn], log, screenshot, `${phase}-answer-${turn + 1}`);
	}
	await waitForReply(page, log, before);
	if (await done().catch(() => false)) return;
	await screenshot(page, `${phase}-not-reached`);
	throw new Error(`${phase}: expected element not shown after ${MAX_TURNS} scripted turns`);
}

async function cleanUp(page: any, log: any) {
	const overlay = page.getByTestId('embed-fullscreen-overlay').last();
	if (await overlay.isVisible().catch(() => false)) {
		await overlay.getByTestId('embed-minimize').click().catch(() => page.keyboard.press('Escape'));
		await expect(overlay).toBeHidden({ timeout: 10_000 }).catch(() => undefined);
	}
	if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log);
}

function locators(page: any) {
	const last = () => page.getByTestId('message-assistant').last();
	const templateCards = () => last().locator(FINISHED).filter({ has: page.getByTestId('slides-template-card') });
	const decks = () => page.locator(FINISHED).filter({ hasNot: page.getByTestId('slides-template-card') });
	return { last, templateCards, decks };
}

/** Press "Use this design" (it sends a chat message); returns the assistant count before it. */
async function pressUseDesign(page: any, overlay: any, chatUrl: string): Promise<number> {
	const before = await assistantCount(page);
	await overlay.getByTestId('slides-template-use').click();
	await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);
	return before;
}

async function begin(page: any, name: string) {
	test.setTimeout(1_500_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger(name);
	const screenshot = createStepScreenshotter(log, { filenamePrefix: name });
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	// Known startup race shared with the isolated slides specs (slides-focus-*.spec.ts, slides-manual-edit.spec.ts).
	allowConsoleErrorPatterns([/WebSocket changed before message dispatch/, /Connection failed, cannot send message: \{type: get_chat_model_preference/]);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	return { log, screenshot };
}

// contract-test: direct surface=gui.web assertions=slides.focus.template-designer
test('template designer focus leads a beginner to a refined, saved template (real inference)', async ({ page }: { page: any }) => {
	const { log, screenshot } = await begin(page, 'slides-focus-real-designer');
	const { templateCards } = locators(page);
	try {
		const briefSent = await sendWithGemini(page, DESIGN_BRIEF, log, screenshot, 'brief');
		// The activated focus shows in the reply's activity summary (assistantActivitySummary.ts).
		await expect(page.getByTestId('assistant-activity-summary-text').filter({ hasText: "Activated 'Design a template'" }).first())
			.toBeVisible({ timeout: 60_000 });
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		const chatUrl = page.url();
		await answerUntil(page, log, screenshot, 'designer', DESIGN_REPLIES, briefSent, async () => (await templateCards().count()) >= 3);
		await screenshot(page, 'designer-three-cards');

		// The designs share one carousel (EmbedPreviewLarge); only the current card is visible.
		let overlay = await openFullscreen(page, await showCarouselCard(locators(page).last(), templateCards().nth(1)));
		await expect(overlay.getByTestId('slides-template-use')).toBeVisible({ timeout: 20_000 });
		await screenshot(page, 'designer-card-open');
		await waitForReply(page, log, await pressUseDesign(page, overlay, chatUrl));
		await screenshot(page, 'designer-design-chosen');

		// The refinement either re-emits the template as a new card or edits the chosen card in
		// place with a diff (design-template SKILL.md, refine phase); both change a card's rendering.
		const allCards = () => page.locator(FINISHED).filter({ has: page.getByTestId('slides-template-card') });
		const cardStates = (): Promise<string[]> => allCards().evaluateAll((cards: Element[]) =>
			cards.map((card) => `${card.getAttribute('data-embed-id')}|${card.innerHTML}`));
		const beforeRefinement = new Set(await cardStates());
		const refinementSent = await sendWithGemini(page, 'Make the headings bigger and the accent a bit warmer.', log, screenshot, 'refinement');
		await waitForReply(page, log, refinementSent);
		let refinedIndex = -1;
		await expect.poll(async () => {
			refinedIndex = (await cardStates()).findIndex((state) => !beforeRefinement.has(state));
			return refinedIndex;
		}, { timeout: 120_000 }).toBeGreaterThanOrEqual(0);
		const refinedCard = allCards().nth(refinedIndex);
		await refinedCard.scrollIntoViewIfNeeded();
		await screenshot(page, 'designer-refined-card');

		overlay = await openFullscreen(page, await showCarouselCard(page.getByTestId('message-assistant').filter({ has: refinedCard }).last(), refinedCard));
		const save = overlay.getByTestId('slides-template-save');
		await expect(save).toBeVisible({ timeout: 20_000 });
		await save.click();
		await expect(save).toContainText(/Saved/i, { timeout: 30_000 });
		await screenshot(page, 'designer-saved');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);
	} finally {
		await cleanUp(page, log);
	}
});

// contract-test: direct surface=gui.web assertions=slides.focus.presentation-planner
test('presentation planner focus takes a beginner from idea to a deck with speaker notes (real inference)', async ({ page }: { page: any }) => {
	const { log, screenshot } = await begin(page, 'slides-focus-real-planner');
	const { last, templateCards, decks } = locators(page);
	try {
		const beginnerSent = await sendWithGemini(page, PLAN_BRIEF, log, screenshot, 'beginner');
		// The activated focus shows in the reply's activity summary (assistantActivitySummary.ts).
		await expect(page.getByTestId('assistant-activity-summary-text').filter({ hasText: "Activated 'Plan a presentation'" }).first())
			.toBeVisible({ timeout: 60_000 });
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		const chatUrl = page.url();

		let designChosen = false;
		await answerUntil(page, log, screenshot, 'planner', PLAN_REPLIES, beginnerSent, async () => {
			if ((await decks().count()) > 0) return true;
			if ((await templateCards().count()) >= 1 && !designChosen) {
				designChosen = true;
				const overlay = await openFullscreen(page, templateCards().first());
				await screenshot(page, 'planner-design-card');
				await waitForReply(page, log, await pressUseDesign(page, overlay, chatUrl));
				return (await decks().count()) > 0;
			}
			return false;
		});
		await expect(decks().first()).toBeVisible({ timeout: ANSWER_TIMEOUT });
		await screenshot(page, 'planner-deck-preview');

		const overlay = await openFullscreen(page, decks().first());
		await expect(overlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		const slideCount = await overlay.getByTestId('slide-strip-item').count();
		log(`deck slides: ${slideCount}`);
		expect(slideCount).toBeGreaterThanOrEqual(5);
		await overlay.getByTestId('slides-edit').click();
		await expect(page.getByTestId('slides-editor')).toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
		// Speaker notes sit behind the toolbar's notes toggle (SlidesEditorToolbar.svelte).
		await page.getByTestId('slides-editor-notes-toggle').click();
		await expect(page.getByTestId('slides-editor-notes')).not.toHaveValue('', { timeout: 20_000 });
		await screenshot(page, 'planner-deck-notes');
		await overlay.getByTestId('slides-edit').click();
		await expect(page.getByTestId('slides-editor')).toHaveCount(0, { timeout: 30_000 });
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);

		const reviewSent = await sendWithGemini(page, 'Yes, please review it.', log, screenshot, 'review');
		await waitForReply(page, log, reviewSent);
		await expect(last()).not.toBeEmpty();
		await screenshot(page, 'planner-review-reply');
	} finally {
		await cleanUp(page, log);
	}
});
