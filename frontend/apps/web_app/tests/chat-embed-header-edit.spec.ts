// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Editing embeds in a chat with the shared header Edit button (web, Rust core build).
 *
 * A real chat turn creates a sheet and a code embed: the signed LIVE_MOCK replay
 * (mercury_routing_fixture.EDITABLE_EMBEDS_PROMPT) only replaces the model
 * provider boundary and returns a markdown table and a python fence, which the
 * real stream consumer turns into embeds. The sheet opens in the same fullscreen
 * as everywhere else; the round pencil at the start of its top bar turns into a
 * round check while editing, and the check saves the change as the next version
 * (embed-user-edits.header.edit-save-button). A reload reads the saved version
 * back from the real backend. A code embed in a chat stays assistant-owned (the
 * server accepts code edits only in Projects), so it shows no Edit button there.
 * An assistant document needs the docs artifact worker, which the isolated CI
 * stack does not run; the document header button in a chat is covered by
 * components/embed-header-edit-button.spec.ts and its save by the Projects spec.
 *
 * Run: ci_coordinator.py submit --mode e2e --spec chat-embed-header-edit.spec.ts
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { reloadChatWorkspace } = require('./helpers/workspace-navigation');

const { email, password, otpKey } = getTestAccount();
const PROMPT = 'Draft a budget table and a greeting script. MERCURY_ROUTING_E2E:editable_embeds <<<TEST_LIVE_MOCK:mercury_auto_low>>>';
const EDITED_COST = '950';

// contract-test: direct surface=gui.web assertions=embed-user-edits.header.edit-save-button,embed-user-edits.edit.next-version
test('a sheet in a chat is edited with the header pencil and saved with its check; chat code has no Edit', async ({ page }: { page: any }) => {
	test.setTimeout(360_000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('CHAT_EMBED_HEADER_EDIT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-embed-header-edit' });

	attachConsoleListeners(page);
	// A socket reconnect during the run makes a housekeeping send meet the closing socket;
	// the client retries it and it is not part of the edit flow (as in videos-generate-chat).
	allowConsoleErrorPatterns([/WebSocket changed before message dispatch/, /Connection failed, cannot send message: \{type: get_chat_model_preference/]);
	attachNetworkListeners(page);
	page.on('console', (message: any) => {
		const textValue = message.text();
		if ((message.type() === 'warning' || message.type() === 'error') && /\[(EmbedSenders|EmbedDiffStore|embedEditSession|SheetEmbedFullscreen)\]/.test(textValue)) {
			log(`Browser ${message.type()}: ${textValue.slice(0, 400)}`);
		}
	});
	await page.setViewportSize({ width: 1440, height: 1000 });
	await installE2EServerContentOverrideGate(page, 'chat-embed-header-edit');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const embedPreview = (appId: string) => page.getByTestId('message-assistant').last()
		.locator(`[data-testid="embed-preview"][data-app-id="${appId}"][data-status="finished"]`).first();
	const open = async (appId: string) => {
		await expect(embedPreview(appId)).toBeVisible({ timeout: 90_000 });
		return openFullscreen(page, embedPreview(appId));
	};
	const cell = (id: string) => page.locator(`[data-testid="sheet-cell"][data-cell="${id}"]`);
	/** Presses the header pencil and checks it became the round check. */
	const startEditing = async (overlay: any, testId: string) => {
		const button = overlay.getByTestId(testId);
		await expect(button).toBeVisible({ timeout: 20_000 });
		await expect(button).toHaveAttribute('data-edit-state', 'edit');
		await button.click();
		await expect(button).toHaveAttribute('data-edit-state', 'save');
		await expect(button.getByTestId('embed-edit-save-icon')).toBeVisible();
	};
	/** Presses the check: the save runs and the button is the pencil again. */
	const finishEditing = async (overlay: any, testId: string) => {
		const button = overlay.getByTestId(testId);
		await button.click();
		await expect(button).toHaveAttribute('data-edit-state', 'edit', { timeout: 60_000 });
	};

	let completed = false;
	try {
		await sendMessage(page, PROMPT, log, screenshot, 'editable-embeds');
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
		const chatUrl = page.url();
		await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
		await screenshot(page, 'chat-with-sheet-and-code');

		// Sheet: the header pencil → edit a cell → the check saves and leaves edit mode.
		let overlay = await open('sheets');
		// The venue cost cell, whichever row the table header maps to.
		const venueCost = page.locator('[data-testid="sheet-cell"]').filter({ hasText: /^1200$/ }).first();
		await expect(venueCost).toBeVisible({ timeout: 30_000 });
		const costCell = await venueCost.getAttribute('data-cell');
		expect(costCell, 'the venue cost cell has an address').toBeTruthy();
		await startEditing(overlay, 'sheet-edit-toggle');
		await cell(costCell!).click();
		const input = page.getByTestId('sheet-cell-input');
		await input.fill(EDITED_COST);
		await input.press('Enter');
		await expect(cell(costCell!)).toHaveText(EDITED_COST);
		await screenshot(page, 'sheet-header-check-editing');
		await finishEditing(overlay, 'sheet-edit-toggle');
		await expect(page.getByTestId('sheet-cell-input')).toHaveCount(0);
		await expect(page.getByTestId('sheet-save-status')).toHaveAttribute('data-state', 'saved', { timeout: 60_000 });
		await screenshot(page, 'sheet-saved');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });

		// Code in a chat stays assistant-owned: same fullscreen, no Edit button.
		overlay = await open('code');
		await expect(overlay).toContainText('def greet(name):', { timeout: 30_000 });
		await expect(overlay.getByTestId('code-edit-button')).toHaveCount(0);
		await screenshot(page, 'code-in-chat-no-edit');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });

		// A reload reads the saved version back from the server.
		await reloadChatWorkspace(page, chatUrl, log);
		overlay = await open('sheets');
		await expect(cell(costCell!)).toHaveText(EDITED_COST, { timeout: 30_000 });
		await screenshot(page, 'sheet-after-reload');
		await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
		completed = true;
	} finally {
		if (!completed) await screenshot(page, 'failure-state');
		if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'cleanup');
	}
});
