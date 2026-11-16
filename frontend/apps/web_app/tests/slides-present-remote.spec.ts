// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and named screenshots cover each checkpoint)
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Presenting a slide deck on a laptop while the same account's phone acts as the remote (web, Rust core build).
 *
 * The deck comes from the signed LIVE_MOCK replay (mercury_routing_fixture.SLIDES_PROMPT). Presenter state
 * travels as `slides_present_state {embed_id, ciphertext}` WebSocket frames relayed to the user's other
 * devices, encrypted with the embed key in the Rust core; the server stores nothing. The fixture deck has no
 * speaker notes, so the notes check covers the toggle state only; the privacy check proves that no relayed
 * frame carries a slide title.
 *
 * Run: ci_coordinator.py submit --mode e2e --web-rust-core --spec slides-present-remote.spec.ts
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen } = require('./helpers/embed-test-helpers');
const { openChatAfterContextSync, waitForContextSyncComplete } = require('./helpers/chat-hydration');

const { email, password, otpKey } = getTestAccount();
const PROMPT = 'Create a two-slide launch plan deck. MERCURY_ROUTING_E2E:slides_deck <<<TEST_LIVE_MOCK:mercury_auto_low>>>';
const SLIDE_TITLES = ['Launch plan', 'Timeline', 'Q4 rollout'];

// contract-test: direct surface=gui.web assertions=slides.present.remote-control,slides.present.remote-relay-private
test('a phone remote steps and jumps the laptop presentation and relays only encrypted state', async ({ browser }: { browser: any }, testInfo: any) => {
	test.setTimeout(480_000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('SLIDES_PRESENT_REMOTE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'slides-present-remote' });
	const baseURL = testInfo.project.use.baseURL ?? process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';

	const laptopContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
	const phoneContext = await browser.newContext({
		baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2
	});
	const laptop = await laptopContext.newPage();
	const phone = await phoneContext.newPage();

	// Every WebSocket frame on both devices; only the presenter-state frames are judged.
	const stateFrames: { direction: 'sent' | 'received'; raw: string }[] = [];
	const watchSockets = (page: any) => page.on('websocket', (socket: any) => {
		const keep = (direction: 'sent' | 'received') => (frame: any) => {
			const raw = typeof frame.payload === 'string' ? frame.payload : String(frame.payload ?? '');
			if (raw.includes('slides_present_state')) stateFrames.push({ direction, raw });
		};
		socket.on('framesent', keep('sent'));
		socket.on('framereceived', keep('received'));
	});
	watchSockets(laptop);
	watchSockets(phone);
	attachConsoleListeners(laptop);
	attachConsoleListeners(phone);
	// Name the source of browser interventions (e.g. preventDefault in a passive listener).
	for (const devicePage of [laptop, phone]) await devicePage.addInitScript(() => {
		const original = Event.prototype.preventDefault;
		Event.prototype.preventDefault = function patched(this: Event) {
			const result = original.call(this);
			// A passive listener's preventDefault is ignored: report which handler tried.
			if (this.cancelable && !this.defaultPrevented) {
				console.warn(`[passive-intervention] ${this.type} on ${(this.currentTarget as Element | null)?.nodeName ?? 'window'}: ${new Error().stack?.split('\n').slice(1, 6).join(' | ')}`);
			}
			return result;
		};
	});
	for (const [device, devicePage] of [['laptop', laptop], ['phone', phone]] as const) {
		devicePage.on('console', (message: any) => {
			if (!/Unable to preventDefault|\[passive-intervention\]/.test(message.text())) return;
			const where = message.location?.() ?? {};
			log(`${device} ${message.text().slice(0, 600)} at ${where.url ?? '?'}:${where.lineNumber ?? '?'}:${where.columnNumber ?? '?'}`);
		});
	}
	allowConsoleErrorPatterns([/WebSocket changed before message dispatch/, /Connection failed, cannot send message: \{type: get_chat_model_preference/]);
	attachNetworkListeners(laptop);

	const attach = async (name: string, page: any) => testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
	const audience = () => laptop.getByTestId('slides-audience');
	const deckPreview = (page: any) => page.getByTestId('message-assistant').last()
		.locator('[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]').first();

	let completed = false;
	try {
		await installE2EServerContentOverrideGate(laptop, 'slides-present-remote-laptop');
		await installE2EServerContentOverrideGate(phone, 'slides-present-remote-phone');

		// 1. Laptop: create the deck, open it fullscreen and start presenting.
		await loginToTestAccount(laptop, log, screenshot);
		await startNewChat(laptop, log);
		await sendMessage(laptop, PROMPT, log, screenshot, 'slides-deck');
		await expect(laptop).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		const chatId = new URL(laptop.url()).hash.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
			?? new URL(laptop.url()).searchParams.get('chat-id');
		expect(chatId, 'the chat id is in the URL').toBeTruthy();
		await waitForAssistantMessage(laptop, { which: 'last', logCheckpoint: log });
		await expect(deckPreview(laptop)).toBeVisible({ timeout: 90_000 });
		const laptopOverlay = await openFullscreen(laptop, deckPreview(laptop));
		await expect(laptopOverlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		await laptopOverlay.getByTestId('slides-present').click();
		await expect(audience()).toBeVisible({ timeout: 20_000 });
		await expect(audience()).toHaveAttribute('data-slide-index', '0');

		// 2. Phone: same account (wait for a fresh TOTP window), same chat, same deck, open the remote.
		await laptop.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
		await loginToTestAccount(phone, log, screenshot);
		await openChatAfterContextSync(phone, chatId, testInfo);
		await waitForContextSyncComplete(phone, testInfo);
		await expect(deckPreview(phone)).toBeVisible({ timeout: 90_000 });
		const phoneOverlay = await openFullscreen(phone, deckPreview(phone));
		await expect(phoneOverlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		await expect(phone.getByTestId('slides-presenting-elsewhere')).toBeVisible({ timeout: 30_000 });
		await phone.getByTestId('slides-remote-open').tap();
		await expect(phone.getByTestId('slides-remote-panel')).toBeVisible();
		await expect(phone.getByTestId('slides-remote-position')).toHaveText('1 / 2', { timeout: 15_000 });
		await expect(phone.getByTestId('slides-remote-not-presenting')).toHaveCount(0);
		await attach('phone-remote-panel', phone);

		// 3. Phone next -> laptop slide 2; jump back to slide 1; notes toggle.
		await phone.getByTestId('slides-remote-next').tap();
		await expect(audience()).toHaveAttribute('data-slide-index', '1', { timeout: 10_000 });
		await expect(phone.getByTestId('slides-remote-position')).toHaveText('2 / 2', { timeout: 10_000 });
		await attach('laptop-presenting-slide-2', laptop);
		await phone.getByTestId('slides-remote-slide-1').tap();
		await expect(audience()).toHaveAttribute('data-slide-index', '0', { timeout: 10_000 });
		const toggle = phone.getByTestId('slides-remote-notes-toggle');
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await toggle.tap();
		await expect(toggle).toHaveAttribute('aria-expanded', 'true');
		await expect(phone.getByTestId('slides-remote-notes')).toBeVisible();
		await toggle.tap();
		await expect(phone.getByTestId('slides-remote-notes')).toHaveCount(0);

		// 4. Laptop ArrowRight -> phone position follows.
		await laptop.keyboard.press('ArrowRight');
		await expect(audience()).toHaveAttribute('data-slide-index', '1', { timeout: 10_000 });
		await expect(phone.getByTestId('slides-remote-position')).toHaveText('2 / 2', { timeout: 10_000 });

		// 5. Laptop leaves the presentation -> phone shows not-presenting.
		await laptop.getByTestId('slides-audience-exit').click();
		await expect(audience()).toHaveCount(0, { timeout: 10_000 });
		await expect(phone.getByTestId('slides-remote-not-presenting')).toBeVisible({ timeout: 30_000 });
		await attach('phone-not-presenting', phone);

		// 6. Privacy: relayed frames are encrypted envelopes without slide text.
		// Sent frames may carry the client's W3C trace id (added to every outgoing frame for
		// tracing); the relay forwards only embed_id and ciphertext to the other device.
		expect(stateFrames.filter((f) => f.direction === 'sent').length, 'a device sent presenter state').toBeGreaterThan(0);
		expect(stateFrames.filter((f) => f.direction === 'received').length, 'a device received relayed state').toBeGreaterThan(0);
		for (const { direction, raw } of stateFrames) {
			const frame = JSON.parse(raw);
			expect(Object.keys(frame).sort()).toEqual(['payload', 'type']);
			expect(frame.type).toBe('slides_present_state');
			const { _traceparent: traceparent, ...payload } = frame.payload;
			expect(Object.keys(payload).sort()).toEqual(['ciphertext', 'embed_id']);
			if (direction === 'received') expect(traceparent, 'the relay forwards no extra fields').toBeUndefined();
			else if (traceparent !== undefined) expect(traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$/);
			for (const title of SLIDE_TITLES) expect(raw).not.toContain(title);
		}
		completed = true;
	} finally {
		if (!completed) {
			await attach('failure-laptop', laptop).catch(() => undefined);
			await attach('failure-phone', phone).catch(() => undefined);
		}
		if (/chat-id=/.test(laptop.url())) await deleteActiveChat(laptop, log, screenshot, 'cleanup').catch(() => undefined);
		await phoneContext.close();
		await laptopContext.close();
	}
});
