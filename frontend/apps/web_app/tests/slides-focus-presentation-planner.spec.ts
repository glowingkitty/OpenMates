/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// proof-video: not_required reason=visual_smoke_not_needed (fixture replay; the result video comes from real-inference-slides-focus-modes.spec.ts on dev)
/**
 * Slides focus mode "Plan a presentation" (web). Real focus activation, Jev phase
 * gates, stream consumer and embeds; only the Jev and model providers are replaced by
 * the signed LIVE_MOCK group `slides_focus` (step token SLIDES_FOCUS_E2E:<step>).
 *
 * "Use this design" is pressed for real; the E2E-gated sessionStorage marker gives that
 * press its step token (slidesTemplateUse.ts), and the sent text is asserted as the user message.
 * The final Template action step needs the deck Template action (slides.templates.apply-to-deck).
 *
 * Run: ci_coordinator.py submit --mode e2e --web-rust-core --spec slides-focus-presentation-planner.spec.ts
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen, closeFullscreen, showCarouselCard } = require('./helpers/embed-test-helpers');

const { email, password, otpKey } = getTestAccount();
const GROUP = '<<<TEST_LIVE_MOCK:slides_focus>>>';
const step = (text: string, id: string) => `${text} SLIDES_FOCUS_E2E:${id} ${GROUP}`;

// contract-test: direct surface=gui.web assertions=slides.focus.presentation-planner,slides.templates.apply-to-deck
test('the presentation planner focus takes a beginner from idea to a reviewed deck', async ({ page }: { page: any }) => {
	test.setTimeout(540_000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('SLIDES_FOCUS_PLANNER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'slides-focus-planner' });
	attachConsoleListeners(page);
	allowConsoleErrorPatterns([/WebSocket changed before message dispatch/, /Connection failed, cannot send message: \{type: get_chat_model_preference/]);
	attachNetworkListeners(page);
	// The version timeline reads the server's version list; log each page so a
	// missing version dot shows whether the stored head or its rows were absent.
	page.on('response', async (response: any) => {
		if (!/\/v1\/embeds\/[^/]+\/versions(\?|$)/.test(response.url())) return;
		const body = await response.json().catch(() => null);
		log('Embed version list read.', {
			status: response.status(),
			currentVersion: body?.current_version ?? null,
			versions: Array.isArray(body?.versions) ? body.versions.map((row: any) => row.version_number) : null
		});
	});
	// The review fix stores the deck as version 2 from the browser; log embed-write
	// warnings and server error frames so a refused store names its reason.
	page.on('console', (message: any) => {
		const textValue = message.text();
		if (((message.type() === 'warning' || message.type() === 'error')
			&& /\[(EmbedSenders|EmbedDiffStore|EmbedVersionTimeline|RustEmbedWrite|ChatSyncService:AI|Slides[A-Za-z]*)\]|embed_|Canonical/.test(textValue))
			|| /\[(EmbedSenders|RustEmbedWrite)\]|is finalized \(status=finished\)|Marked embed .* as processed/.test(textValue)) {
			log(`Browser ${message.type()}: ${textValue.slice(0, 400)}`);
		}
	});
	// Embed write frames (type, embed id, version only; never ciphertext) show whether
	// the version 2 head was sent and what the server answered.
	const frameSummary = (payload: string) => {
		const field = (name: string) => payload.match(new RegExp(`"${name}"\\s*:\\s*("[^"]{0,80}"|\\d+|null)`))?.[1] ?? '-';
		return `type=${field('type')} embed=${field('embed_id')} version=${field('version_number')} status=${field('status')} code=${field('code')} reason=${field('reason')}`;
	};
	const EMBED_FRAME = /"type"\s*:\s*"(store_embed[a-z_]*|send_embed_data|embed_[a-z_]*|error|recovery_[a-z_]*)"/;
	// Typed recovery delivers an AI revision of a stored root embed (version N+1);
	// log each offered output and the final chunk's recovery fields.
	const recoverySummary = (payload: string) => {
		const outputs = [...payload.matchAll(/"subject_id"\s*:\s*"([^"]{0,80})"[^}]*?"output_kind"\s*:\s*"([a-z]+)"[^}]*?"output_version"\s*:\s*(\d+)/g)]
			.map((match) => `${match[2]}:${match[1].slice(0, 8)}:v${match[3]}`);
		return outputs.length ? ` outputs=${outputs.join(',')}` : '';
	};
	page.on('websocket', (socket: any) => {
		socket.on('framereceived', (frame: any) => {
			const payload = typeof frame.payload === 'string' ? frame.payload : '';
			if (payload.startsWith('{"type":"error"') || payload.includes('"type": "error"')) log(`Server error frame: ${payload.slice(0, 300)}`);
			else if (EMBED_FRAME.test(payload.slice(0, 200))) log(`Embed frame received: ${frameSummary(payload)}${recoverySummary(payload)}`);
			else if (/"is_final_chunk"\s*:\s*true/.test(payload)) {
				const field = (name: string) => payload.match(new RegExp(`"${name}"\\s*:\\s*("[^"]{0,40}"|\\d+|true|false|null)`))?.[1] ?? '-';
				log(`Final chunk: recovery_protocol_version=${field('recovery_protocol_version')} recovery_provisional=${field('recovery_provisional')} focus_continuation=${field('is_focus_mode_continuation')}`);
			}
		});
		socket.on('framesent', (frame: any) => {
			const payload = typeof frame.payload === 'string' ? frame.payload : '';
			if (EMBED_FRAME.test(payload.slice(0, 200))) log(`Embed frame sent: ${frameSummary(payload)}${recoverySummary(payload)}`);
		});
	});
	await page.setViewportSize({ width: 1440, height: 1000 });
	await installE2EServerContentOverrideGate(page, 'slides-focus-planner');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const last = () => page.getByTestId('message-assistant').last();
	const finished = '[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]';
	const templateCards = () => last().locator(finished).filter({ has: page.getByTestId('slides-template-card') });
	const deckPreview = () => last().locator(finished).filter({ hasNot: page.getByTestId('slides-template-card') }).first();
	const anyDeck = () => page.locator(finished).filter({ hasNot: page.getByTestId('slides-template-card') });
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
		await reply('@focus:slides:plan_presentation I need slides for my hackathon project but I don\'t know how to start', 'p1', 'beginner');
		// The activated focus shows in the reply's activity summary (assistantActivitySummary.ts).
		await expect(page.getByTestId('assistant-activity-summary-text').filter({ hasText: "Activated 'Plan a presentation'" }).first())
			.toBeVisible({ timeout: 60_000 });
		await expect(last()).toContainText('Three simple questions');
		await screenshot(page, 'planner-goal-questions');
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		chatUrl = page.url();

		await reply('Win the jury for a pilot, five minutes on stage, mostly engineers. Yes, that summary is right.', 'p2', 'goal-answers');
		await expect(last()).toContainText('problem, demo, solution, impact, ask');
		// GSLQ7: the replayed reply starts with a copied Focus activation toon block;
		// it is dropped, so no code embed or its fields show in the reply.
		await expect(last().locator('[data-testid="embed-preview"][data-app-id="code"]')).toHaveCount(0);
		await expect(last()).not.toContainText('focus_mode_name');
		await screenshot(page, 'planner-story-arc');

		await reply('Sounds good, use that story.', 'p3', 'arc-confirmed');
		// The outline renders as an ordered list (numbers are list markers, not text).
		await expect(last().locator('ol > li')).toHaveCount(6);
		await expect(last().locator('ol > li').nth(5)).toContainText('The ask');
		await screenshot(page, 'planner-outline');

		await reply('can the demo come before the solution?', 'p4', 'outline-change');
		await expect(last().locator('ol > li')).toHaveCount(6);
		await expect(last().locator('ol > li').nth(2)).toContainText('The demo');
		await expect(anyDeck()).toHaveCount(0);
		await screenshot(page, 'planner-outline-updated-no-deck');

		await reply('Yes, that outline is right.', 'p5', 'outline-confirmed');
		// The built-in designs share one carousel (EmbedPreviewLarge); only the current card is visible.
		await expect.poll(async () => templateCards().count(), { timeout: 90_000 }).toBeGreaterThanOrEqual(3);
		await screenshot(page, 'planner-builtin-templates');

		const boldPitch = await showCarouselCard(last(), templateCards().filter({ hasText: 'Bold pitch' }));
		let overlay = await openFullscreen(page, boldPitch);
		await pressUseDesign(overlay, 'Use the design "Bold pitch"');
		await expect(deckPreview()).toBeVisible({ timeout: 90_000 });
		overlay = await openFullscreen(page, deckPreview());
		await expect(overlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		await expect(overlay.getByTestId('slide-strip-item')).toHaveCount(6);
		await expect(overlay.getByTestId('slide-position')).toContainText('1 / 6');
		await expect(overlay.getByTestId('version-dot-2')).toHaveCount(0);
		// Speaker notes of the first slide are shown in the editor's notes field.
		await overlay.getByTestId('slides-edit').click();
		await expect(page.getByTestId('slides-editor')).toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
		// Speaker notes sit behind the toolbar's notes toggle (SlidesEditorToolbar.svelte).
		await page.getByTestId('slides-editor-notes-toggle').click();
		await expect(page.getByTestId('slides-editor-notes')).toHaveValue(/Greet the jury/);
		await overlay.getByTestId('slides-edit').click();
		await expect(page.getByTestId('slides-editor')).toHaveCount(0, { timeout: 30_000 });
		await screenshot(page, 'planner-deck-six-slides-notes');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);

		await reply('Yes, please review it.', 'p7', 'review');
		await expect(last()).toContainText('slide 2');
		await screenshot(page, 'planner-review-findings');
		await reply('Yes, apply that fix.', 'p8', 'accept-fix');
		await expect(last()).toContainText('shortened the slide 2 title');
		// The reply text can finish before the diff's version row is stored, and the
		// timeline reads the version list once per open: reopen until version 2 is listed.
		await expect(async () => {
			overlay = await openFullscreen(page, anyDeck().first());
			const listed = await overlay.getByTestId('version-dot-2').waitFor({ state: 'visible', timeout: 10_000 })
				.then(() => true, () => false);
			if (!listed) {
				await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl }).catch(() => undefined);
				throw new Error('version 2 not listed yet');
			}
		}).toPass({ timeout: 90_000, intervals: [2_000, 5_000] });
		await screenshot(page, 'planner-deck-version-two');

		// Template action step (slides.templates.apply-to-deck).
		await overlay.getByTestId('slides-deck-template-action').click();
		await expect(page.getByTestId('slides-template-picker')).toBeVisible({ timeout: 20_000 });
		await page.locator('[data-testid="slides-template-option"][data-template-id="builtin:clean-business"]').click();
		await page.getByTestId('slides-template-apply').click();
		await expect(overlay.getByTestId('version-dot-3')).toBeVisible({ timeout: 60_000 });
		await screenshot(page, 'planner-template-applied');
		completed = true;
	} finally {
		if (!completed) await screenshot(page, 'failure-state');
		if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'cleanup');
	}
});
