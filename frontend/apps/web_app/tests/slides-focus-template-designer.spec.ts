/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// proof-video: not_required reason=visual_smoke_not_needed (fixture replay; the result video comes from real-inference-slides-focus-modes.spec.ts on dev)
/**
 * Slides focus mode "Design a template" (web). A real chat runs the real focus
 * activation, Jev phase gates, stream consumer and embed service; only the Jev and
 * model providers are replaced by the signed LIVE_MOCK group `slides_focus`
 * (backend/apps/ai/testing/slides_focus_fixture.py, step token SLIDES_FOCUS_E2E:<step>).
 *
 * "Use this design" is pressed for real; the E2E-gated sessionStorage marker gives that
 * press its step token (slidesTemplateUse.ts), and the sent text is asserted as the user message.
 *
 * Run: ci_coordinator.py submit --mode e2e --web-rust-core --spec slides-focus-template-designer.spec.ts
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen, closeFullscreen, showCarouselCard } = require('./helpers/embed-test-helpers');

const { email, password, otpKey } = getTestAccount();
const GROUP = '<<<TEST_LIVE_MOCK:slides_focus>>>';
const step = (text: string, id: string) => `${text} SLIDES_FOCUS_E2E:${id} ${GROUP}`;
const LAYOUTS = ['title', 'section', 'content', 'image', 'quote', 'closing'];

// contract-test: direct surface=gui.web assertions=slides.focus.template-designer,slides.templates.library
test('the template designer focus guides from brief to a saved design and a first deck', async ({ page }: { page: any }) => {
	test.setTimeout(480_000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('SLIDES_FOCUS_TEMPLATE_DESIGNER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'slides-focus-template-designer' });
	attachConsoleListeners(page);
	allowConsoleErrorPatterns([/WebSocket changed before message dispatch/, /Connection failed, cannot send message: \{type: get_chat_model_preference/]);
	attachNetworkListeners(page);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await installE2EServerContentOverrideGate(page, 'slides-focus-template-designer');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const last = () => page.getByTestId('message-assistant').last();
	const templateCards = () => last().locator('[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]')
		.filter({ has: page.getByTestId('slides-template-card') });
	const deckPreview = () => last().locator('[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]')
		.filter({ hasNot: page.getByTestId('slides-template-card') }).first();
	const reply = async (text: string, id: string, label: string) => {
		await sendMessage(page, step(text, id), log, screenshot, label);
		await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	};

	// The real "Use this design" press: it sends the app's own text, and the E2E-gated
	// sessionStorage key adds the group marker as `test_mock_marker`; the replay fixture
	// maps the named design to its step (slides_focus_fixture._DESIGN_USE_STEPS).
	const pressUseDesign = async (overlay: any, message: string) => {
		await page.evaluate(([key, value]: string[]) => sessionStorage.setItem(key, value), ['openmates:e2e-send-marker', GROUP]);
		await overlay.getByTestId('slides-template-use').click();
		await page.evaluate((key: string) => sessionStorage.removeItem(key), 'openmates:e2e-send-marker');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);
		await expect(page.getByTestId('message-user').last()).toContainText(
			// The app quotes the design name typographically (“Bold pitch”).
			new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/"/g, '["“”]')),
			{ timeout: 30_000 },
		);
		await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	};

	let chatUrl = '';
	let completed = false;
	try {
		await reply('@focus:slides:design_template Design a slide template for our youth sports club, our colours are green and white', 'd1', 'brief');
		// The activated focus shows in the reply's activity summary (assistantActivitySummary.ts).
		await expect(page.getByTestId('assistant-activity-summary-text').filter({ hasText: "Activated 'Design a template'" }).first())
			.toBeVisible({ timeout: 60_000 });
		await expect(last()).toContainText('Three quick questions');
		await screenshot(page, 'designer-questions');
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		chatUrl = page.url();

		await reply('Parents and players, add a warm yellow, no logo. Yes, that summary is right, show me designs.', 'd2', 'answers');
		await expect(templateCards()).toHaveCount(3, { timeout: 90_000 });
		await screenshot(page, 'designer-three-cards');

		// The three designs share one carousel (EmbedPreviewLarge); only the current card is visible.
		const secondCard = await showCarouselCard(last(), templateCards().filter({ hasText: 'Night Match' }));
		let overlay = await openFullscreen(page, secondCard);
		for (const layout of LAYOUTS) await expect(overlay.getByTestId(`slides-template-layout-${layout}`)).toBeVisible({ timeout: 20_000 });
		await expect(overlay.getByTestId('slides-template-save')).toBeVisible();
		await screenshot(page, 'designer-card-two-layouts');
		await pressUseDesign(overlay, 'Use the design "Night Match"');
		await expect(templateCards()).toHaveCount(1, { timeout: 90_000 });
		await screenshot(page, 'designer-refined-card');

		await reply('Looks great, it is finished. Please save it.', 'd4', 'finish');
		await expect(last()).toContainText('Press Save');
		overlay = await openFullscreen(page, templateCards().first().or(page.locator('[data-testid="embed-preview"][data-app-id="slides"]').filter({ has: page.getByTestId('slides-template-card') }).last()));
		await expect(overlay.getByTestId('slides-template-save')).toBeVisible({ timeout: 20_000 });
		await overlay.getByTestId('slides-template-save').click();
		await expect(overlay.getByTestId('slides-template-save')).toContainText(/Saved/i, { timeout: 30_000 });
		await screenshot(page, 'designer-saved');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);

		await reply('Yes, make a first deck about our summer camp.', 'd5', 'first-deck');
		await expect(deckPreview()).toBeVisible({ timeout: 90_000 });
		overlay = await openFullscreen(page, deckPreview());
		await expect(overlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		await expect(overlay.getByTestId('slide-strip-item')).toHaveCount(3);
		// The renderer exposes the theme as CSS custom properties on the slide canvas.
		const accent = await overlay.getByTestId('slide-canvas').first().locator('.slide-canvas')
			.evaluate((el: Element) => getComputedStyle(el).getPropertyValue('--slide-color-accent').trim());
		expect(accent.toLowerCase()).toBe('#4ade80');
		await screenshot(page, 'designer-first-deck');
		completed = true;
	} finally {
		if (!completed) await screenshot(page, 'failure-state');
		if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'cleanup');
	}
});
