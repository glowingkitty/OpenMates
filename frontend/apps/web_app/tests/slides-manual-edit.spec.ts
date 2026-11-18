// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Manual slide deck edit saved as a new embed version (web, Rust core build).
 *
 * A real chat turn creates the deck: the signed LIVE_MOCK replay
 * (mercury_routing_fixture.SLIDES_PROMPT) only replaces the Jev and model
 * provider boundaries and returns a ```slides fence, which the real stream
 * consumer normalises into a deck embed. The edit then runs in the shared
 * Worker's Rust core (deck replica, operations, markup), Done stores the edited
 * deck as version 2 through the client core's user revision commit (which also
 * writes the "Slides edited · version 2" chat event, embed-user-edits
 * event.chat-notice), and a reload reads both back from the real backend.
 *
 * Run: ci_coordinator.py submit --mode e2e --web-rust-core --spec slides-manual-edit.spec.ts
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen } = require('./helpers/embed-test-helpers');
const { reloadChatWorkspace } = require('./helpers/workspace-navigation');
const { closeFullscreen } = require('./helpers/embed-test-helpers');

const { email, password, otpKey } = getTestAccount();
const PROMPT = 'Create a two-slide launch plan deck. MERCURY_ROUTING_E2E:slides_deck <<<TEST_LIVE_MOCK:mercury_auto_low>>>';
const EDITED_TITLE = 'Launch day';

// contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation,slides.editor.save-checked-version,chats.persistence.client-encrypted,embed-user-edits.edit.next-version,embed-user-edits.event.chat-notice
test('a manual deck edit is saved as a new version and survives a reload', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('SLIDES_MANUAL_EDIT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'slides-manual-edit' });

	attachConsoleListeners(page);
	// A socket reconnect during the run makes a housekeeping send meet the closing socket;
	// the client retries it and it is not part of the edit flow (as in videos-generate-chat).
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
	page.on('console', (message: any) => {
		const textValue = message.text();
		if ((message.type() === 'warning' || message.type() === 'error') && /\[(EmbedSenders|EmbedDiffStore|EmbedVersionTimeline|embedEditSession|Slides[A-Za-z]*)\]|Post-admission|Canonical embed/.test(textValue)) {
			log(`Browser ${message.type()}: ${textValue.slice(0, 400)}`);
		}
	});
	// The save is the client core's user revision commit; its chat event row
	// ("Slides edited · version N") proves which version the server took.
	const editNotices = () => page.locator('[data-testid="embed-updated-event"][data-action="edit"]');
	await page.setViewportSize({ width: 1440, height: 1000 });
	await installE2EServerContentOverrideGate(page, 'slides-manual-edit');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const deckPreview = () => page.getByTestId('message-assistant').last()
		.locator('[data-testid="embed-preview"][data-app-id="slides"][data-status="finished"]').first();
	const editor = () => page.getByTestId('slides-editor');
	const hit = (id: string) => page.locator(`[data-testid="slides-editor-element"][data-element-id="${id}"]`);
	const openDeck = async () => {
		await expect(deckPreview()).toBeVisible({ timeout: 90_000 });
		const overlay = await openFullscreen(page, deckPreview());
		await expect(overlay.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 20_000 });
		return overlay;
	};
	const openEditor = async (overlay: any) => {
		// Edit exists only in the Rust-core build and for a stored deck embed.
		await expect(overlay.getByTestId('slides-edit')).toBeVisible({ timeout: 20_000 });
		await overlay.getByTestId('slides-edit').click();
		await expect(editor(), 'the Rust core should open the deck').toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
	};

	let completed = false;
	try {
		await sendMessage(page, PROMPT, log, screenshot, 'slides-deck');
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		const chatUrl = page.url();
		await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });

		let overlay = await openDeck();
		await expect(overlay.getByTestId('slide-strip-item')).toHaveCount(2);
		await expect(overlay.getByTestId('slide-canvas').first()).toContainText('Launch plan');
		// A fresh assistant deck is version 1: no timeline yet.
		await expect(overlay.getByTestId('embed-version-timeline')).toHaveCount(0);
		await screenshot(page, 'deck-version-1');

		await openEditor(overlay);
		// Change the title text on slide 1.
		await hit('e1').dblclick();
		const input = page.getByTestId('slides-editor-text-input');
		await expect(input).toBeFocused();
		await page.keyboard.press('ControlOrMeta+a');
		await page.keyboard.type(EDITED_TITLE);
		await page.keyboard.press('Escape');
		// Move the shape on slide 2 by one arrow-key step (10 canvas units).
		await page.locator('[data-testid="slides-editor-strip-item"][data-slide-id="s2"]').click();
		await expect(editor()).toHaveAttribute('data-slide-id', 's2');
		await expect(hit('e4')).toHaveAttribute('data-x', '80');
		await hit('e4').click();
		await page.keyboard.press('ArrowRight');
		await expect(hit('e4')).toHaveAttribute('data-x', '90');
		await expect(editor()).toHaveAttribute('data-dirty', 'true');
		await screenshot(page, 'deck-editing');

		// The header Edit button is now the round check: it saves and leaves edit mode.
		await expect(overlay.getByTestId('slides-edit')).toHaveAttribute('data-edit-state', 'save');
		await overlay.getByTestId('slides-edit').click();
		await expect(editor()).toHaveCount(0, { timeout: 30_000 });
		await expect(overlay.getByTestId('slides-edit')).toHaveAttribute('data-edit-state', 'edit');
		await expect(page.getByTestId('slides-editor-save-failed')).toHaveCount(0);
		await expect(overlay.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
		await expect(overlay.getByTestId('version-dot-1')).toBeVisible();
		await overlay.getByTestId('slide-strip-item').first().click();
		await expect(overlay.getByTestId('slide-canvas').first()).toContainText(EDITED_TITLE);
		await screenshot(page, 'deck-saved-version-2');

		// The open deck adds its embed deep link to the URL; reload the plain chat like the diagram spec does.
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
		// embed-user-edits.event.chat-notice: the chat shows the edit as one quiet row, without a reload.
		await expect(editNotices()).toHaveCount(1, { timeout: 60_000 });
		await expect(editNotices().first()).toContainText('2');
		await expect(editNotices().first()).toHaveAttribute('data-change-count', '1');
		await expect(page.locator('[data-testid="message-system"]').filter({ hasText: '"embed_updated"' })).toHaveCount(0);
		await screenshot(page, 'deck-edit-chat-notice');
		await reloadChatWorkspace(page, chatUrl, log);
		await expect(editNotices()).toHaveCount(1, { timeout: 90_000 });
		overlay = await openDeck();
		await expect(overlay.getByTestId('slide-canvas').first()).toContainText(EDITED_TITLE, { timeout: 30_000 });
		await expect(overlay.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
		await expect(overlay.getByTestId('version-dot-1')).toBeVisible();
		await expect(overlay.getByTestId('version-dot-3')).toHaveCount(0);
		await screenshot(page, 'deck-after-reload');

		// The stored head is the edited deck: the moved shape reopens where it was left,
		// and Done without a change writes no further version.
		await openEditor(overlay);
		await page.locator('[data-testid="slides-editor-strip-item"][data-slide-id="s2"]').click();
		await expect(hit('e4')).toHaveAttribute('data-x', '90');
		await expect(editor()).toHaveAttribute('data-dirty', 'false');
		await overlay.getByTestId('slides-edit').click();
		await expect(editor()).toHaveCount(0);
		await expect(overlay.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
		await expect(overlay.getByTestId('version-dot-3')).toHaveCount(0);
		// An unchanged Done writes no further version, so no further chat event either.
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
		await expect(editNotices()).toHaveCount(1);
		await expect(editNotices().first()).toHaveAttribute('data-change-count', '1');
		await expect(editNotices().first()).toContainText('2');
		completed = true;
	} finally {
		// Playwright's own failure screenshot is taken after cleanup; keep the failing state.
		if (!completed) await screenshot(page, 'failure-state');
		if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'cleanup');
	}
});
