/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)

/**
 * Slides focus modes (real inference, dev server only): "Design a template" and
 * "Plan a presentation" run with Gemini 3.8 Flash and the real Jev phase gates. A third
 * case presents a real Gemini deck on a laptop and steers it from a phone remote (same
 * account, relayed encrypted presenter state).
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
const { openChatAfterContextSync, waitForContextSyncComplete } = require('./helpers/chat-hydration');

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

const userCount = (page: any): Promise<number> => page.getByTestId('message-user').count();
const BUSY_STATUSES = ['sending', 'queued', 'processing', 'streaming', 'waiting_for_internet', 'waiting_for_upload'];
const SETTLED_FOR_MS = 6000;

/**
 * Insert the Gemini 3.8 Flash mention through the dropdown, then send the text after it.
 * Returns the user message count before the send, for waitForReply.
 */
async function sendWithGemini(page: any, prompt: string, log: any, screenshot: any, label: string): Promise<number> {
	const before = await userCount(page);
	const editor = page.getByTestId('message-field').last().getByTestId('message-editor');
	await expect(editor).toBeVisible();
	const busySince = Date.now();
	const sendButton = page.getByTestId('message-field').last().getByTestId('composer-send-button');
	await expect.poll(async () => {
		const busy = (await sendButton.count()) > 0 && (await sendButton.last().getAttribute('aria-busy')) === 'true';
		const leftover = ((await editor.textContent()) ?? '').trim();
		return busy || leftover.length > 0;
	}, { timeout: 180_000 }).toBe(false);
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
 * Chat state in DOM order: whether a user message beyond `usersBefore` exists, whether the last
 * message is an assistant reply after the newest user message, and whether anything is still
 * sending, processing or streaming.
 */
function readChatState(page: any, usersBefore: number) {
	return page.evaluate(({ usersBefore, busyStatuses }: { usersBefore: number; busyStatuses: string[] }) => {
		const rows = [...document.querySelectorAll<HTMLElement>(
			'[data-testid="message-user"], [data-testid="message-assistant"], [data-testid="pending-assistant-response"]'
		)];
		const roles = rows.map((row) => row.dataset.testid);
		const users = roles.filter((role) => role === 'message-user').length;
		const lastUser = roles.lastIndexOf('message-user');
		const lastRow = rows[rows.length - 1];
		const busy = rows.some((row) => busyStatuses.includes(row.dataset.status ?? ''))
			|| Boolean(document.querySelector('[data-testid="typing-indicator"]'));
		const replied = lastRow?.dataset.testid === 'message-assistant' && rows.length - 1 > lastUser
			&& Boolean(lastRow.querySelector('[data-testid="generated-by"]'));
		return { sent: users > usersBefore, replied, busy, users };
	}, { usersBefore, busyStatuses: BUSY_STATUSES });
}

/**
 * Wait until the reply to the test's own message is finished: our user message is in the chat and
 * no longer sending, the last message is a finished assistant reply after it (model label shown),
 * nothing is processing, and this holds for SETTLED_FOR_MS so a focus continuation that starts a
 * moment after a reply is not mistaken for the end of the turn.
 */
async function waitForReply(page: any, log: any, usersBefore: number) {
	let settledSince = 0;
	await expect.poll(async () => {
		const state = await readChatState(page, usersBefore);
		if (!state.sent || !state.replied || state.busy) {
			settledSince = 0;
			return false;
		}
		settledSince ||= Date.now();
		return Date.now() - settledSince >= SETTLED_FOR_MS;
	}, { timeout: ANSWER_TIMEOUT, intervals: [1000] }).toBe(true);
	const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
	await expect(generatedBy).toContainText(MODEL_NAME);
	log(`reply generated by: ${(await generatedBy.textContent())?.trim()}`);
}

/**
 * A focus mention first returns the activation card, then the focus mode's first question from the
 * auto-confirmed continuation. Wait for that question like a person would; answering during it
 * races the continuation.
 */
async function waitForFocusQuestion(page: any, log: any, briefSent: number) {
	await expect.poll(async () => {
		const text = await page.getByTestId('message-assistant').last().innerText().catch(() => '');
		return text.includes('?');
	}, { timeout: ANSWER_TIMEOUT }).toBe(true);
	await waitForReply(page, log, briefSent);
}

/**
 * Return once `done` is true after the current reply; otherwise send the next scripted answer and
 * wait for the reply to it. Fails clearly when the expected element is still missing.
 */
async function answerUntil(page: any, log: any, screenshot: any, phase: string, replies: string[],
	done: () => Promise<boolean>) {
	for (let turn = 0; turn <= replies.length && turn < MAX_TURNS; turn++) {
		if (await done().catch(() => false)) return;
		if (turn >= replies.length) break;
		await screenshot(page, `${phase}-turn-${turn + 1}`);
		await waitForReply(page, log, await sendWithGemini(page, replies[turn], log, screenshot, `${phase}-answer-${turn + 1}`));
	}
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

/** Press "Use this design" (it sends a chat message); returns the user message count before it. */
async function pressUseDesign(page: any, overlay: any, chatUrl: string): Promise<number> {
	const before = await userCount(page);
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
		await waitForFocusQuestion(page, log, briefSent);
		await answerUntil(page, log, screenshot, 'designer', DESIGN_REPLIES, async () => (await templateCards().count()) >= 3);
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
		await waitForFocusQuestion(page, log, beginnerSent);
		await answerUntil(page, log, screenshot, 'planner', PLAN_REPLIES, async () => {
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

const REMOTE_PROMPT =
	'Create a three-slide deck for our school robotics club season: goals, highlights, next steps. Add short speaker notes.';

// contract-test: direct surface=gui.web assertions=slides.present.remote-control
test('a phone remote steers the laptop presentation of a real deck (real inference)', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
	const { log, screenshot } = await begin(page, 'slides-remote-real');
	const { decks } = locators(page);
	const phoneContext = await browser.newContext({
		baseURL: testInfo.project.use.baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
		deviceScaleFactor: 2, recordVideo: { dir: testInfo.outputPath('phone-video'), size: { width: 390, height: 844 } }
	});
	const phone = await phoneContext.newPage();
	attachConsoleListeners(phone);
	const audience = () => page.getByTestId('slides-audience');
	try {
		await waitForReply(page, log, await sendWithGemini(page, REMOTE_PROMPT, log, screenshot, 'remote-deck'));
		await expect(decks().first()).toBeVisible({ timeout: ANSWER_TIMEOUT });
		const chatId = new URL(page.url()).hash.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
			?? new URL(page.url()).searchParams.get('chat-id');
		expect(chatId, 'the chat id is in the URL').toBeTruthy();
		const laptopOverlay = await openFullscreen(page, decks().first());
		await expect(laptopOverlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		const slideCount = await laptopOverlay.getByTestId('slide-strip-item').count();
		log(`deck slides: ${slideCount}`);
		expect(slideCount).toBeGreaterThanOrEqual(2);
		await laptopOverlay.getByTestId('slides-present').click();
		await expect(audience()).toHaveAttribute('data-slide-index', '0', { timeout: 20_000 });
		await screenshot(page, 'remote-laptop-presenting');

		// Phone: same account in a fresh TOTP window, same chat and deck, open the remote.
		await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
		await loginToTestAccount(phone, log, screenshot);
		await openChatAfterContextSync(phone, chatId, testInfo);
		await waitForContextSyncComplete(phone, testInfo);
		const phoneDeck = phone.locator(FINISHED).filter({ hasNot: phone.getByTestId('slides-template-card') }).first();
		await expect(phoneDeck).toBeVisible({ timeout: 90_000 });
		await openFullscreen(phone, phoneDeck);
		await expect(phone.getByTestId('slides-presenting-elsewhere')).toBeVisible({ timeout: 30_000 });
		await phone.getByTestId('slides-remote-open').tap();
		await expect(phone.getByTestId('slides-remote-position')).toHaveText(`1 / ${slideCount}`, { timeout: 15_000 });
		await screenshot(phone, 'remote-phone-panel');

		// Phone next and jump steer the laptop; laptop keys move the phone; notes on demand.
		await phone.getByTestId('slides-remote-next').tap();
		await expect(audience()).toHaveAttribute('data-slide-index', '1', { timeout: 10_000 });
		await screenshot(page, 'remote-laptop-slide-2');
		await phone.getByTestId(`slides-remote-slide-${slideCount}`).tap();
		await expect(audience()).toHaveAttribute('data-slide-index', String(slideCount - 1), { timeout: 10_000 });
		await phone.getByTestId('slides-remote-slide-1').tap();
		await expect(audience()).toHaveAttribute('data-slide-index', '0', { timeout: 10_000 });
		await phone.getByTestId('slides-remote-notes-toggle').tap();
		await expect(phone.getByTestId('slides-remote-notes')).toBeVisible();
		await screenshot(phone, 'remote-phone-notes');
		await page.keyboard.press('ArrowRight');
		await expect(phone.getByTestId('slides-remote-position')).toHaveText(`2 / ${slideCount}`, { timeout: 10_000 });
		await page.getByTestId('slides-audience-exit').click();
		await expect(phone.getByTestId('slides-remote-not-presenting')).toBeVisible({ timeout: 30_000 });
		await screenshot(phone, 'remote-phone-not-presenting');
	} finally {
		await phoneContext.close().catch(() => undefined);
		await cleanUp(page, log);
	}
});
