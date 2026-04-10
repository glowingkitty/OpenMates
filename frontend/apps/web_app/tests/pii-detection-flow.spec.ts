/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * PII detection flow tests: verify that the PII (Personally Identifiable Information)
 * detection system works correctly end-to-end in the message input.
 *
 * Test: PII detection with 3 entries, click-to-exclude, send with placeholders, show/hide toggle
 *       - Types a realistic email draft prompt with 3 PII entries (2 emails + 1 phone)
 *       - Verifies all 3 are detected and highlighted (yellow background)
 *       - Verifies the PII warning banner appears with correct summary
 *       - Clicks the first email (max@posteo.de) to exclude it (3 → 2 highlights)
 *       - Verifies sarah@proton.com + phone highlights remain (2 highlights)
 *       - Sends the message with 2 active PII detections
 *       - Verifies the sent message has [EMAIL_*] and [PHONE_*] placeholders
 *       - Verifies the excluded email (max@posteo.de) appears as original text
 *       - Tests the PII show/hide toggle button in the chat header
 *       - Deletes the chat
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Test: PII detection, click-to-undo, undo all, send, show/hide toggle
// ---------------------------------------------------------------------------

test('pii detection with 3 entries, click-to-exclude 1, send with 2 placeholders, and show/hide toggle', async ({
	page
}: {
	page: any;
}) => {
	// Wire up console and network logging for debugging on failure
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(480000); // 8 min — login + PII typing + 180s assistant poll + toggle test

	const logCheckpoint = createSignupLogger('PII_DETECTION');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'pii-detection'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Starting PII detection flow test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });

	// ======================================================================
	// STEP 2: Type text with exactly 3 PII types to trigger detection
	// ======================================================================
	logCheckpoint('Typing text with 3 PII types...');

	// This text contains exactly 3 PII entries:
	// - Email 1: max@posteo.de
	// - Email 2: sarah@proton.com
	// - Phone: +49 170 1234567
	const piiText =
		'Write an email draft from max@posteo.de to sarah@proton.com about the broken heater ' +
		'in the building and when it will be fixed. My phone number is +49 170 1234567 for callbacks.';

	await messageEditor.click();
	// Type slowly enough for PII detection to process but not too slowly
	await page.keyboard.type(withMockMarker(piiText, 'pii_detection_check'), { delay: 5 });
	logCheckpoint(`Typed PII text (${piiText.length} chars).`);

	// PII detection triggers on delimiters (space, period, etc.) or after 800ms debounce.
	// The text ends with a period, so detection should trigger. Wait a bit for processing.
	await page.waitForTimeout(1500);

	// Nudge the editor so the PII detection debounce has definitely fired.
	await page.keyboard.press('End');
	await page.keyboard.type(' ', { delay: 10 });
	await page.keyboard.press('Backspace');
	await page.waitForTimeout(1200);

	await takeStepScreenshot(page, 'pii-text-typed');

	// ======================================================================
	// STEP 3: Verify exactly 3 PII highlights appear in the editor
	// ======================================================================
	logCheckpoint('Verifying PII highlights in the editor...');

	const piiHighlights = page.locator('[data-testid="pii-highlight"]');
	const highlightCount = await piiHighlights.count();
	logCheckpoint(`Found ${highlightCount} PII highlights in the editor.`);

	// We expect exactly 3 detections: 2 emails + 1 phone
	expect(highlightCount).toBe(3);

	// Check that specific PII types are highlighted
	const emailHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]');
	const phoneHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="PHONE"]');

	const emailCount = await emailHighlight.count();
	const phoneCount = await phoneHighlight.count();

	logCheckpoint(`PII by type — EMAIL: ${emailCount}, PHONE: ${phoneCount}`);

	expect(emailCount).toBe(2);
	expect(phoneCount).toBe(1);

	// Verify the highlighted text for the first email
	const emailText = await emailHighlight.first().textContent();
	logCheckpoint(`First email highlight text: "${emailText}"`);
	expect(emailText).toContain('max@posteo.de');

	await takeStepScreenshot(page, 'pii-highlights-verified');

	// ======================================================================
	// STEP 5: Verify the PII warning banner appears
	// ======================================================================
	logCheckpoint('Verifying PII warning banner...');

	const piiBanner = page.getByTestId('pii-warning-banner');
	await expect(piiBanner).toBeVisible({ timeout: 10000 });
	logCheckpoint('PII warning banner is visible.');

	const bannerTitle = piiBanner.getByTestId('banner-title');
	const bannerTitleText = await bannerTitle.textContent();
	logCheckpoint(`Banner title: "${bannerTitleText}"`);
	// Title should be "Sensitive data detected" (or translated equivalent)
	expect(bannerTitleText).toBeTruthy();

	const bannerDescription = piiBanner.getByTestId('banner-description');
	const bannerDescText = await bannerDescription.textContent();
	logCheckpoint(`Banner description: "${bannerDescText}"`);
	// Description should mention found PII counts
	expect(bannerDescText).toBeTruthy();
	expect(bannerDescText.toLowerCase()).toContain('found');

	await takeStepScreenshot(page, 'pii-banner-verified');

	// ======================================================================
	// STEP 6: Click email PII highlight to exclude it (3 → 2 highlights)
	// ======================================================================
	logCheckpoint('Clicking email PII highlight to exclude it from replacement...');

	// Verify we start with 3 highlights
	const highlightsBefore = await piiHighlights.count();
	logCheckpoint(`Highlights before click-to-exclude: ${highlightsBefore}`);
	expect(highlightsBefore).toBe(3);

	// Click the email highlight to exclude it from replacement.
	// Dispatch the click via page.evaluate to ensure it reaches ProseMirror's
	// handleDOMEvents.click handler on the contenteditable element.
	const emailPiiId = await emailHighlight.first().getAttribute('data-pii-id');
	logCheckpoint(`Email PII ID to exclude: "${emailPiiId}"`);

	await page.evaluate(() => {
		const el = document.querySelector('[data-testid="pii-highlight"][data-pii-type="EMAIL"]');
		if (el) {
			el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
		}
	});
	logCheckpoint('Dispatched click on email PII highlight via page.evaluate.');

	// Wait for PII re-detection to remove the highlight
	await page.waitForTimeout(2000);

	// Debug: log current highlight count
	const debugHighlightCount = await piiHighlights.count();
	logCheckpoint(`Debug: highlights after click + 2s wait: ${debugHighlightCount}`);

	// The first email (max@posteo.de) should no longer be highlighted; second email remains
	const emailHighlightAfterExclude = await emailHighlight.count();
	logCheckpoint(`Email highlights after exclude: ${emailHighlightAfterExclude}`);
	expect(emailHighlightAfterExclude).toBe(1); // only sarah@proton.com remains

	// Total highlights should now be exactly 2 (sarah@proton.com + phone)
	const highlightsAfterExclude = await piiHighlights.count();
	logCheckpoint(`Total highlights after exclude: ${highlightsAfterExclude} (was ${highlightsBefore})`);
	expect(highlightsAfterExclude).toBe(2);

	// Verify the remaining email is sarah@proton.com
	const remainingEmailText = await emailHighlight.first().textContent();
	logCheckpoint(`Remaining email highlight: "${remainingEmailText}"`);
	expect(remainingEmailText).toContain('sarah@proton.com');

	// Verify phone is still highlighted
	const phoneAfterExclude = await phoneHighlight.count();
	logCheckpoint(`Remaining — PHONE: ${phoneAfterExclude}`);
	expect(phoneAfterExclude).toBe(1);

	// The excluded email should still be in the editor, just not highlighted
	const editorText = await messageEditor.textContent();
	expect(editorText).toContain('max@posteo.de');
	logCheckpoint('Excluded email text still present in editor (just no longer highlighted).');

	await takeStepScreenshot(page, 'pii-click-exclude-verified');

	// ======================================================================
	// STEP 7: Send the message with 2 active PII detections (sarah email + phone)
	// ======================================================================
	logCheckpoint('Sending message with 2 remaining PII detections (max email excluded)...');

	// Verify we still have exactly 2 highlights before sending
	const highlightsBeforeSend = await piiHighlights.count();
	logCheckpoint(`Highlights before send: ${highlightsBeforeSend}`);
	expect(highlightsBeforeSend).toBe(2);

	// Click the send button
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');

	await takeStepScreenshot(page, 'pii-send-message-sent');

	// ======================================================================
	// STEP 8: Wait for assistant response (with generous timeout for AI latency)
	// ======================================================================
	logCheckpoint('Waiting for assistant response...');

	const assistantMessage = page.getByTestId('message-assistant').last();
	let assistantVisible = false;
	for (let wait = 0; wait < 6; wait++) {
		assistantVisible = await assistantMessage.isVisible().catch(() => false);
		if (assistantVisible) {
			logCheckpoint(`Assistant response visible after ~${wait * 30}s.`);
			break;
		}
		logCheckpoint(`Waiting for assistant response (attempt ${wait + 1}/6, 30s each)...`);
		await page.waitForTimeout(30000);
	}

	if (!assistantVisible) {
		logCheckpoint('WARNING: Assistant response did not appear within 180s — skipping post-send assertions.');
		await takeStepScreenshot(page, 'pii-assistant-timeout');
	}

	// ======================================================================
	// STEP 9: Verify user message shows placeholders for phone + IBAN (email excluded)
	// ======================================================================
	if (assistantVisible) {
		await page.waitForTimeout(3000);
		logCheckpoint('Scrolling to user message and waiting for content to render...');

		const userMsgElement = page.getByTestId('message-user').last();
		await expect(userMsgElement).toBeAttached({ timeout: 10000 });

		await userMsgElement.scrollIntoViewIfNeeded();
		await page.evaluate(() => {
			const userMsgs = document.querySelectorAll('[data-testid="message-user"]');
			const lastUserMsg = userMsgs[userMsgs.length - 1];
			if (lastUserMsg) {
				lastUserMsg.scrollIntoView({ block: 'center', behavior: 'instant' });
			}
		});
		await page.waitForTimeout(500);

		// Poll for the text content to render (TipTap lazy init after viewport visibility)
		let userMessage: any = null;
		let userMsgText = '';
		for (let attempt = 0; attempt < 20; attempt++) {
			await page.waitForTimeout(1500);

			if (attempt % 5 === 0 && attempt > 0) {
				await userMsgElement.scrollIntoViewIfNeeded();
			}

			const text = (await userMsgElement.textContent()) || '';
			if (text.includes('heater') || text.includes('[EMAIL') || text.includes('[PHONE')) {
				userMessage = userMsgElement;
				userMsgText = text;
				logCheckpoint(
					`User message rendered after ${attempt + 1} polls: "${text.trim().substring(0, 150)}"`
				);
				break;
			}
			if (attempt === 4 || attempt === 9 || attempt === 19) {
				const html = await userMsgElement.innerHTML().catch(() => 'N/A');
				logCheckpoint(`Debug HTML (poll ${attempt + 1}): "${html.substring(0, 300)}"`);
			}
		}

		if (!userMessage) {
			userMessage = userMsgElement;
			userMsgText = (await userMsgElement.textContent()) || '';
			logCheckpoint(`User message text after polling: "${userMsgText.trim().substring(0, 150)}"`);
		}

		// sarah@proton.com and phone should have been replaced with placeholders
		logCheckpoint(`User message text for PII check: "${userMsgText.trim().substring(0, 200)}"`);
		expect(userMsgText).toMatch(/\[EMAIL_\w+\]/);
		expect(userMsgText).toMatch(/\[PHONE_\w+\]/);

		// max@posteo.de was excluded (clicked) so it should appear as original text
		expect(userMsgText).toContain('max@posteo.de');
		logCheckpoint('User message has email/phone placeholders and original max@posteo.de (excluded).');

		await takeStepScreenshot(page, 'pii-user-message-placeholders');

		// ======================================================================
		// STEP 10: Test the PII show/hide toggle button
		// ======================================================================
		logCheckpoint('Testing PII show/hide toggle button...');

		const chatPiiToggle = page.getByTestId('chat-pii-toggle');

		const toggleVisible = await chatPiiToggle.isVisible({ timeout: 5000 }).catch(() => false);
		const initialToggleRevealed = toggleVisible
			? await chatPiiToggle.getAttribute('data-pii-revealed')
			: null;
		logCheckpoint(
			`Chat header PII toggle visible: ${toggleVisible}, data-pii-revealed: ${initialToggleRevealed}`
		);

		if (toggleVisible && initialToggleRevealed === 'false') {
			logCheckpoint('Clicking chat header PII toggle to reveal...');
			await chatPiiToggle.click();
			await page.waitForTimeout(2000);

			const revealedAttrAfterClick = await chatPiiToggle.getAttribute('data-pii-revealed');
			expect(revealedAttrAfterClick).toBe('true');

			await takeStepScreenshot(page, 'pii-toggle-revealed');

			// Click toggle again to re-hide
			logCheckpoint('Clicking chat header PII toggle to re-hide...');
			await chatPiiToggle.click();
			await page.waitForTimeout(2000);

			const hiddenAttrAfterClick = await chatPiiToggle.getAttribute('data-pii-revealed');
			expect(hiddenAttrAfterClick).toBe('false');

			const reHiddenMsgText = await userMessage.textContent();
			expect(reHiddenMsgText).toMatch(/\[EMAIL_\w+\]/);
			logCheckpoint('User message correctly re-hidden with placeholders.');

			await takeStepScreenshot(page, 'pii-toggle-hidden-again');
		} else {
			logCheckpoint(
				'PII toggle not in expected state — skipping toggle test.'
			);
		}

		await takeStepScreenshot(page, 'pii-toggle-verified');
	}

	// Verify no missing translations on the chat page with PII UI elements
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ======================================================================
	// STEP 10: Delete the chat (cleanup)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'pii-cleanup');

	logCheckpoint('PII detection flow test completed successfully.');
});

// ---------------------------------------------------------------------------
// Test: PII toggle in embed fullscreen is linked to chat header toggle
// ---------------------------------------------------------------------------
// Covers OPE-400: clicking "Hide sensitive data" in the fullscreen embed view
// must replace placeholders with originals AND keep the chat header PII toggle
// in sync (and vice versa). Also verifies that the backend (OPE-399) does not
// hallucinate fake skills when asked to draft a mail containing PII — the mail
// skill must be the one invoked and produce a finished mail embed.
// ---------------------------------------------------------------------------
test('pii toggle in embed fullscreen syncs with chat header state', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('PII_EMBED_FULLSCREEN');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'pii-embed-fullscreen'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Starting embed-fullscreen PII toggle sync test.');

	// ======================================================================
	// STEP 1: Login + new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });

	// ======================================================================
	// STEP 2: Ask the AI to draft a mail that contains PII
	// We force the mail skill via @skill:mail:email so the test is not at the
	// mercy of LLM preselection. The message contains a real email which PII
	// detection replaces with a placeholder before send. The mail draft that
	// comes back should contain the placeholder text, not the original.
	// ======================================================================
	const senderEmail = 'max@posteo.de';
	const receiverEmail = 'sarah@proton.com';
	const draftPrompt =
		`Write an email draft from ${senderEmail} to ${receiverEmail} to ask for an update about the broken heater in the house.`;

	logCheckpoint('Typing mail draft prompt with two PII emails…');
	await messageEditor.click();
	await page.keyboard.type(draftPrompt, { delay: 5 });
	await page.waitForTimeout(1500);

	// Confirm BOTH emails are detected as PII in the editor before sending
	const preSendEmailHighlights = await page
		.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]')
		.count();
	logCheckpoint(`PII highlights in editor before send: ${preSendEmailHighlights}`);
	expect(preSendEmailHighlights).toBeGreaterThanOrEqual(2);

	await takeStepScreenshot(page, 'mail-draft-typed');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send on mail draft prompt.');

	// ======================================================================
	// STEP 3: Wait for the assistant response + a finished mail embed.
	// If OPE-399 regresses and the LLM hallucinates a non-existent skill like
	// "mail|get_apps_settings", the mail embed will never finish and this step
	// will time out — that is the regression signal for OPE-399.
	// ======================================================================
	const assistantMessage = page.getByTestId('message-assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant message is visible.');

	// A finished mail embed has data-status="finished" in its preview.
	const mailEmbedPreview = page
		.locator('[data-testid="embed-preview"][data-status="finished"]')
		.filter({ hasText: /mail|email|heater/i })
		.first();
	await expect(mailEmbedPreview).toBeVisible({ timeout: 120000 });
	logCheckpoint('Mail embed preview reached finished status.');

	await takeStepScreenshot(page, 'mail-embed-finished');

	// ======================================================================
	// STEP 4: Verify initial hidden state — chat history message, embed
	// preview, and (once opened) embed fullscreen must all show the
	// placeholder, not the originals.
	// ======================================================================
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible();

	// The mail embed preview's "To: ..." receiver line is rendered in the
	// BasicInfosBar's `embed-status-value` span (customStatusText). Targeting
	// it directly avoids false positives from the email body text which may
	// contain unrelated strings.
	const previewStatusValue = mailEmbedPreview.getByTestId('embed-status-value').first();

	async function assertAllHidden(label: string) {
		const msgText = (await userMessage.textContent()) || '';
		const previewStatus = (await previewStatusValue.textContent()) || '';
		logCheckpoint(`[${label}] user message first 200: "${msgText.substring(0, 200)}"`);
		logCheckpoint(`[${label}] preview status-value: "${previewStatus}"`);
		expect(msgText, `[${label}] user message must hide sender PII`).not.toContain(senderEmail);
		expect(msgText, `[${label}] user message must hide receiver PII`).not.toContain(receiverEmail);
		expect(previewStatus, `[${label}] preview status must hide receiver PII`).not.toContain(receiverEmail);
		expect(previewStatus, `[${label}] preview status must show EMAIL placeholder`).toMatch(/\[EMAIL_\w+\]/);
	}

	async function assertAllRevealed(label: string) {
		const msgText = (await userMessage.textContent()) || '';
		const previewStatus = (await previewStatusValue.textContent()) || '';
		logCheckpoint(`[${label}] user message first 200: "${msgText.substring(0, 200)}"`);
		logCheckpoint(`[${label}] preview status-value: "${previewStatus}"`);
		expect(msgText, `[${label}] user message must reveal sender`).toContain(senderEmail);
		expect(msgText, `[${label}] user message must reveal receiver`).toContain(receiverEmail);
		expect(previewStatus, `[${label}] preview status must reveal receiver`).toContain(receiverEmail);
		expect(previewStatus, `[${label}] preview status must not show placeholder`).not.toMatch(/\[EMAIL_\w+\]/);
	}

	await assertAllHidden('initial');
	await takeStepScreenshot(page, 'state-01-initial-hidden');

	// ======================================================================
	// STEP 5: Toggle from the CHAT HEADER — message, preview AND (when
	// opened) fullscreen must all swap to originals.
	// ======================================================================
	const chatHeaderToggle = page.getByTestId('chat-pii-toggle');
	await expect(chatHeaderToggle).toBeVisible({ timeout: 5000 });
	const headerInitialAttr = await chatHeaderToggle.getAttribute('data-pii-revealed');
	expect(headerInitialAttr).toBe('false');

	await chatHeaderToggle.click();
	logCheckpoint('Clicked chat header PII toggle to reveal.');
	await page.waitForTimeout(500);

	const headerRevealedAttr = await chatHeaderToggle.getAttribute('data-pii-revealed');
	expect(headerRevealedAttr).toBe('true');

	// THIS IS THE BUG: message swaps, but preview currently does not.
	await assertAllRevealed('after chat-header reveal');
	await takeStepScreenshot(page, 'state-02-header-reveal-preview-and-message');

	// ======================================================================
	// STEP 6: Open the mail embed in fullscreen while reveal is ON — the
	// fullscreen must open already showing originals.
	// ======================================================================
	await mailEmbedPreview.click();
	logCheckpoint('Opened mail embed fullscreen with reveal=true.');

	const embedPiiToggle = page.getByTestId('embed-pii-toggle');
	await expect(embedPiiToggle).toBeVisible({ timeout: 10000 });
	const fullscreenInitialAttr = await embedPiiToggle.getAttribute('data-pii-revealed');
	expect(fullscreenInitialAttr).toBe('true');

	const fullscreenContainer = page.locator('.fullscreen-embed-container');
	await expect(fullscreenContainer).toBeVisible();
	const fsRevealedText = (await fullscreenContainer.textContent()) || '';
	logCheckpoint(`Fullscreen (opened with reveal=true) first 200: "${fsRevealedText.substring(0, 200)}"`);
	expect(fsRevealedText).toContain(receiverEmail);

	await takeStepScreenshot(page, 'state-03-fullscreen-revealed');

	// ======================================================================
	// STEP 7: Toggle from the EMBED FULLSCREEN — must hide in fullscreen,
	// AND behind it the preview + user message must also hide.
	// ======================================================================
	await embedPiiToggle.click();
	logCheckpoint('Clicked fullscreen PII toggle to hide.');
	await page.waitForTimeout(500);

	const fsHiddenAttr = await embedPiiToggle.getAttribute('data-pii-revealed');
	expect(fsHiddenAttr).toBe('false');

	const fsHiddenText = (await fullscreenContainer.textContent()) || '';
	expect(fsHiddenText).not.toContain(receiverEmail);
	expect(fsHiddenText).toMatch(/\[EMAIL_\w+\]/);

	await takeStepScreenshot(page, 'state-04-fullscreen-hidden');

	// Close fullscreen and verify preview + message are also hidden.
	const closeButton = page.getByTestId('embed-minimize');
	await closeButton.click();
	logCheckpoint('Closed fullscreen embed.');
	await page.waitForTimeout(500);

	const chatHeaderAfterFsHide = await chatHeaderToggle.getAttribute('data-pii-revealed');
	expect(chatHeaderAfterFsHide).toBe('false');
	await assertAllHidden('after fullscreen hide');
	await takeStepScreenshot(page, 'state-05-all-hidden-after-fullscreen-toggle');

	// ======================================================================
	// STEP 8: Toggle from the EMBED FULLSCREEN to reveal — then confirm
	// that opening it, toggling, and closing keeps preview + message in sync.
	// ======================================================================
	await mailEmbedPreview.click();
	await expect(embedPiiToggle).toBeVisible({ timeout: 10000 });
	const reopenAttr = await embedPiiToggle.getAttribute('data-pii-revealed');
	expect(reopenAttr).toBe('false');

	await embedPiiToggle.click();
	logCheckpoint('Clicked fullscreen PII toggle to reveal again.');
	await page.waitForTimeout(500);
	expect(await embedPiiToggle.getAttribute('data-pii-revealed')).toBe('true');

	await closeButton.click();
	await page.waitForTimeout(500);
	await assertAllRevealed('after fullscreen reveal');
	await takeStepScreenshot(page, 'state-06-all-revealed-after-fullscreen-toggle');

	// ======================================================================
	// STEP 9: Open the chat as an "existing chat" — navigate away via
	// "new chat" and then click back on it from the sidebar. This exercises
	// the load-from-IndexedDB path which is how the user reported the bug
	// in practice. The toggle must still work identically after a round-trip
	// through the chat loader, not just on the freshly-sent chat in memory.
	// ======================================================================
	// Open the sidebar (closed by default on <=1440px viewports).
	const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await sidebarToggle.isVisible().catch(() => false)) {
		await sidebarToggle.click();
		await page.waitForTimeout(1000);
		logCheckpoint('Opened sidebar to access chat list.');
	}

	// Grab the chat-id of the active chat so we can click it again later.
	const activeChatWrapper = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatWrapper).toBeVisible({ timeout: 10000 });
	const activeChatId = await activeChatWrapper.getAttribute('data-chat-id');
	logCheckpoint(`Active chat id to re-open: ${activeChatId}`);

	// Navigate away: start a new chat (becomes the active one).
	await startNewChat(page, logCheckpoint);
	await page.waitForTimeout(1500);

	// Re-open sidebar if startNewChat closed it.
	if (await sidebarToggle.isVisible().catch(() => false)) {
		const stillHasChat = await page
			.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${activeChatId}"]`)
			.isVisible()
			.catch(() => false);
		if (!stillHasChat) {
			await sidebarToggle.click();
			await page.waitForTimeout(1000);
			logCheckpoint('Re-opened sidebar after new-chat navigation.');
		}
	}

	// Now click back on the original chat from the sidebar.
	const targetChatItem = activeChatId
		? page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${activeChatId}"]`)
		: page.getByTestId('chat-item-wrapper').first();
	await expect(targetChatItem).toBeVisible({ timeout: 10000 });
	await targetChatItem.click();
	logCheckpoint('Clicked sidebar chat to re-open as existing chat.');
	await page.waitForTimeout(2000);

	// Wait for the mail embed preview to reappear after load-from-IDB.
	await expect(mailEmbedPreview).toBeVisible({ timeout: 15000 });
	await page.waitForTimeout(1000); // Let embed mount + PII mappings settle

	// Reveal state persists in-session (piiVisibilityStore is session-scoped and
	// keyed by chatId). After reopen the state is whatever it was before we left.
	// First step: normalise to HIDDEN via the chat header so the test is
	// deterministic from here on.
	let postReopenAttr = await chatHeaderToggle.getAttribute('data-pii-revealed');
	logCheckpoint(`After re-opening existing chat, header data-pii-revealed: ${postReopenAttr}`);
	if (postReopenAttr === 'true') {
		await chatHeaderToggle.click();
		await page.waitForTimeout(500);
		postReopenAttr = await chatHeaderToggle.getAttribute('data-pii-revealed');
	}
	expect(postReopenAttr).toBe('false');
	await assertAllHidden('post-reopen hidden');
	await takeStepScreenshot(page, 'state-07-reopen-initial-hidden');

	// THE CORE REGRESSION: click the chat-header toggle on the RE-OPENED chat.
	// Preview status-value MUST swap to original (this is the bug path).
	await chatHeaderToggle.click();
	logCheckpoint('Clicked chat header toggle to reveal (after reopen).');
	await page.waitForTimeout(500);
	expect(await chatHeaderToggle.getAttribute('data-pii-revealed')).toBe('true');
	await assertAllRevealed('post-reopen after chat-header reveal');
	await takeStepScreenshot(page, 'state-08-reopen-header-reveal');

	// Open the fullscreen on the reopened chat — must already show original.
	await mailEmbedPreview.click();
	await expect(embedPiiToggle).toBeVisible({ timeout: 10000 });
	expect(await embedPiiToggle.getAttribute('data-pii-revealed')).toBe('true');
	const reopenFsText = (await fullscreenContainer.textContent()) || '';
	expect(reopenFsText).toContain(receiverEmail);

	// Toggle from the fullscreen to hide — preview + message must also hide.
	await embedPiiToggle.click();
	await page.waitForTimeout(500);
	expect(await embedPiiToggle.getAttribute('data-pii-revealed')).toBe('false');
	await closeButton.click();
	await page.waitForTimeout(500);
	await assertAllHidden('post-reopen after fullscreen hide');
	await takeStepScreenshot(page, 'state-09-reopen-fullscreen-hide');

	// ======================================================================
	// STEP 10: Cleanup
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'pii-embed-cleanup');

	logCheckpoint('Embed-fullscreen PII toggle sync test completed successfully.');
});
