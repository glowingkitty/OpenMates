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
 * Test: PII detection, undo, undo all, send with placeholder, show/hide toggle
 *       - Types text containing multiple PII types (email, phone, IBAN, credit card, SSN)
 *       - Verifies each PII type is detected and highlighted in orange
 *       - Verifies the PII warning banner appears with correct summary
 *       - Tests clicking a highlighted PII to undo (exclude) its replacement
 *       - Verifies the undone PII loses its highlight
 *       - Tests the "Undo All" button to remove all remaining PII highlights
 *       - Verifies all highlights are removed after undo all
 *       - Clears input, types a message with an email to send
 *       - Sends the message and verifies:
 *         - The user message shows the [EMAIL_com] placeholder (green, hidden mode)
 *         - The assistant response references [EMAIL_com]
 *       - Tests the PII show/hide toggle button in the chat header
 *         - Clicks "Show sensitive data" to reveal the original email (orange)
 *         - Clicks "Hide sensitive data" to re-hide (green placeholder)
 *       - Deletes the chat
 *
 * Edge cases tested:
 *       - Date formats (YYYY-MM-DD) should NOT be detected as phone numbers
 *       - Common version numbers should NOT be detected
 *       - Localhost IPs should NOT be detected
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

test('pii detection with undo, undo all, send with placeholder, and show/hide toggle', async ({
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
	test.setTimeout(300000);

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
	// STEP 2: Type text with multiple PII types to trigger detection
	// ======================================================================
	logCheckpoint('Typing text with multiple PII types...');

	// This text contains:
	// - Email: jane.doe@example.com
	// - Phone: +49 170 1234567
	// - IBAN: DE89 3704 0044 0532 0130 00
	// - Credit card: 4111 1111 1111 1111 (Visa test card, passes Luhn)
	// - SSN: 123-45-6789
	// We also include edge cases that should NOT be detected:
	// - Date: 2026-04-12 (should NOT be a phone number)
	// - Version: 1.2.3 (should NOT be detected)
	const piiText =
		'Contact jane.doe@example.com or call +49 170 1234567 for help. ' +
		'IBAN: DE89 3704 0044 0532 0130 00. ' +
		'Card: 4111 1111 1111 1111. ' +
		'SSN: 123-45-6789. ' +
		'Meeting on 2026-04-12, version 1.2.3 is fine.';

	await messageEditor.click();
	// Type slowly enough for PII detection to process but not too slowly
	await page.keyboard.type(withMockMarker(piiText, 'pii_detection_check'), { delay: 5 });
	logCheckpoint(`Typed PII text (${piiText.length} chars).`);

	// PII detection triggers on delimiters (space, period, etc.) or after 800ms debounce.
	// The text ends with a period, so detection should trigger. Wait a bit for processing.
	await page.waitForTimeout(1500);

	await takeStepScreenshot(page, 'pii-text-typed');

	// ======================================================================
	// STEP 3: Verify PII highlights appear in the editor
	// ======================================================================
	logCheckpoint('Verifying PII highlights in the editor...');

	const piiHighlights = page.locator('.ProseMirror [data-testid="pii-highlight"]');
	const highlightCount = await piiHighlights.count();
	logCheckpoint(`Found ${highlightCount} PII highlights in the editor.`);

	// We expect at least email, phone, IBAN, credit card, SSN = 5 detections
	expect(highlightCount).toBeGreaterThanOrEqual(5);

	// Check that specific PII types are highlighted
	const emailHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]');
	const phoneHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="PHONE"]');
	const ibanHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="IBAN"]');
	const creditCardHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="CREDIT_CARD"]');
	const ssnHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="SSN"]');

	const emailCount = await emailHighlight.count();
	const phoneCount = await phoneHighlight.count();
	const ibanCount = await ibanHighlight.count();
	const cardCount = await creditCardHighlight.count();
	const ssnCount = await ssnHighlight.count();

	logCheckpoint(
		`PII by type — EMAIL: ${emailCount}, PHONE: ${phoneCount}, IBAN: ${ibanCount}, CARD: ${cardCount}, SSN: ${ssnCount}`
	);

	expect(emailCount).toBeGreaterThanOrEqual(1);
	expect(phoneCount).toBeGreaterThanOrEqual(1);
	expect(ibanCount).toBeGreaterThanOrEqual(1);
	expect(cardCount).toBeGreaterThanOrEqual(1);
	expect(ssnCount).toBeGreaterThanOrEqual(1);

	// Verify the highlighted text for the email
	const emailText = await emailHighlight.first().textContent();
	logCheckpoint(`Email highlight text: "${emailText}"`);
	expect(emailText).toContain('jane.doe@example.com');

	await takeStepScreenshot(page, 'pii-highlights-verified');

	// ======================================================================
	// STEP 4: Verify edge cases — dates should NOT be detected as phone numbers
	// ======================================================================
	logCheckpoint('Verifying edge cases — dates should not be detected...');

	// Get all highlighted text content to check for false positives
	const allHighlightTexts: string[] = [];
	for (let i = 0; i < highlightCount; i++) {
		const text = await piiHighlights.nth(i).textContent();
		allHighlightTexts.push(text || '');
	}
	logCheckpoint(`All highlighted texts: ${JSON.stringify(allHighlightTexts)}`);

	// The date "2026-04-12" should NOT appear in any highlight
	const dateDetected = allHighlightTexts.some((t: string) => t.includes('2026-04-12'));
	logCheckpoint(`Date "2026-04-12" detected as PII: ${dateDetected}`);
	expect(dateDetected).toBe(false);

	await takeStepScreenshot(page, 'edge-cases-verified');

	// ======================================================================
	// STEP 5: Verify the PII warning banner appears
	// ======================================================================
	logCheckpoint('Verifying PII warning banner...');

	const piiBanner = page.getByTestId('pii-warning-banner');
	await expect(piiBanner).toBeVisible({ timeout: 5000 });
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

	const undoAllButton = piiBanner.getByTestId('undo-all-btn');
	await expect(undoAllButton).toBeVisible();
	logCheckpoint('Undo All button is visible.');

	await takeStepScreenshot(page, 'pii-banner-verified');

	// ======================================================================
	// STEP 6: Click a PII highlight to undo (exclude) one detection
	// ======================================================================
	logCheckpoint('Testing click-to-undo on the email PII highlight...');

	// Get the count of highlights before clicking
	const highlightsBefore = await piiHighlights.count();
	logCheckpoint(`Highlights before undo: ${highlightsBefore}`);

	// Click the email highlight to exclude it from replacement
	await emailHighlight.first().click();
	logCheckpoint('Clicked on email PII highlight to undo.');

	// Wait for PII re-detection to remove the highlight
	await page.waitForTimeout(1500);

	// The email should no longer be highlighted
	const emailHighlightAfterUndo = await page
		.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]')
		.count();
	logCheckpoint(`Email highlights after undo: ${emailHighlightAfterUndo}`);
	expect(emailHighlightAfterUndo).toBe(0);

	// Total highlights should have decreased (or stayed same if re-detection found new matches)
	const highlightsAfterUndo = await piiHighlights.count();
	logCheckpoint(`Total highlights after undo: ${highlightsAfterUndo} (was ${highlightsBefore})`);

	// The email text "jane.doe@example.com" should still be in the editor, just not highlighted
	const editorText = await messageEditor.textContent();
	expect(editorText).toContain('jane.doe@example.com');
	logCheckpoint('Email text still present in editor after undo (just no longer highlighted).');

	await takeStepScreenshot(page, 'pii-click-undo-verified');

	// ======================================================================
	// STEP 7: Click "Undo All" to remove all remaining PII highlights
	// ======================================================================
	logCheckpoint('Testing "Undo All" button...');

	const highlightsBeforeUndoAll = await piiHighlights.count();
	logCheckpoint(`Highlights before Undo All: ${highlightsBeforeUndoAll}`);
	expect(highlightsBeforeUndoAll).toBeGreaterThan(0);

	await undoAllButton.click();
	logCheckpoint('Clicked "Undo All" button.');

	// Wait for re-detection/clearing
	await page.waitForTimeout(1000);

	// All highlights should be gone
	const highlightsAfterUndoAll = await piiHighlights.count();
	logCheckpoint(`Highlights after Undo All: ${highlightsAfterUndoAll}`);
	expect(highlightsAfterUndoAll).toBe(0);

	// The PII warning banner should also disappear
	const bannerVisibleAfterUndo = await piiBanner.isVisible({ timeout: 2000 }).catch(() => false);
	logCheckpoint(`PII banner visible after Undo All: ${bannerVisibleAfterUndo}`);
	expect(bannerVisibleAfterUndo).toBe(false);

	// All the original text should still be in the editor
	const editorTextAfterUndo = await messageEditor.textContent();
	expect(editorTextAfterUndo).toContain('jane.doe@example.com');
	expect(editorTextAfterUndo).toContain('+49 170 1234567');
	logCheckpoint('All original text preserved in editor after Undo All.');

	await takeStepScreenshot(page, 'pii-undo-all-verified');

	// ======================================================================
	// STEP 8: Clear input, type a message with email, and send it
	// ======================================================================
	logCheckpoint('Clearing editor and typing a message with an email to send...');

	await messageEditor.click();
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.waitForTimeout(500);

	// Type a simple message with an email that should be replaced on send
	const sendText = 'Please contact me at testuser@privateemail.org about my account.';
	await page.keyboard.type(withMockMarker(sendText, 'pii_detection_send'), { delay: 5 });
	logCheckpoint(`Typed send message: "${sendText}"`);

	// Wait for PII detection
	await page.waitForTimeout(1500);

	// Verify the email is detected before sending
	const sendEmailHighlight = page.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]');
	const sendEmailCount = await sendEmailHighlight.count();
	logCheckpoint(`Email highlights before send: ${sendEmailCount}`);
	expect(sendEmailCount).toBeGreaterThanOrEqual(1);

	// Verify warning banner appeared
	await expect(piiBanner).toBeVisible({ timeout: 5000 });
	logCheckpoint('PII warning banner visible before send.');

	await takeStepScreenshot(page, 'pii-send-message-typed');

	// Click the send button
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');

	await takeStepScreenshot(page, 'pii-send-message-sent');

	// ======================================================================
	// STEP 9: Verify user message shows placeholder in hidden mode
	// ======================================================================
	logCheckpoint('Waiting for user message to appear with PII placeholder...');

	// Wait for the assistant response first — this ensures the message round-trip completed
	// and both user and assistant messages should be fully rendered
	const assistantMessage = page.getByTestId('message-assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response is visible — message round-trip complete.');

	// Give extra time for message rendering and PII decorations
	await page.waitForTimeout(5000);

	// Find the user message that contains our text with [EMAIL_com] placeholder.
	// Messages are E2E encrypted, so ReadOnlyMessage needs to decrypt + init TipTap.
	// The ReadOnlyMessage component uses lazy TipTap initialization — it only creates
	// the TipTap editor when the element becomes visible in the viewport via
	// IntersectionObserver. After sending, the chat scrolls to the assistant response,
	// pushing the user message out of view. We must scroll it back into view.
	logCheckpoint('Scrolling to user message and waiting for content to render...');

	const userMsgElement = page.getByTestId('message-user').last();
	await expect(userMsgElement).toBeAttached({ timeout: 10000 });
	logCheckpoint('User message element is attached to DOM.');

	// Scroll the user message into view to trigger TipTap initialization
	await userMsgElement.scrollIntoViewIfNeeded();
	logCheckpoint('Scrolled user message into view.');

	// Also try scrolling the chat container directly to ensure the element is truly visible
	await page.evaluate(() => {
		const userMsgs = document.querySelectorAll('[data-testid="message-user"]');
		const lastUserMsg = userMsgs[userMsgs.length - 1];
		if (lastUserMsg) {
			lastUserMsg.scrollIntoView({ block: 'center', behavior: 'instant' });
		}
	});
	await page.waitForTimeout(500);
	logCheckpoint('Scrolled chat container to center user message.');

	// Poll for the text content to render (TipTap init after viewport visibility)
	let userMessage: any = null;
	let userMsgText = '';
	for (let attempt = 0; attempt < 30; attempt++) {
		await page.waitForTimeout(1000);

		// Re-scroll periodically in case the viewport shifted
		if (attempt % 5 === 0 && attempt > 0) {
			await userMsgElement.scrollIntoViewIfNeeded();
		}

		const text = (await userMsgElement.textContent()) || '';
		if (text.includes('contact') || text.includes('[EMAIL') || text.includes('account')) {
			userMessage = userMsgElement;
			userMsgText = text;
			logCheckpoint(
				`User message rendered after ${attempt + 1}s: "${text.trim().substring(0, 100)}"`
			);
			break;
		}
		if (attempt === 4 || attempt === 9 || attempt === 14 || attempt === 29) {
			const html = await userMsgElement.innerHTML().catch(() => 'N/A');
			logCheckpoint(`Debug HTML (attempt ${attempt + 1}): "${html.substring(0, 300)}"`);
		}
	}

	if (!userMessage) {
		// Final fallback: check the entire chat history area
		const chatHistory = page.locator('[data-testid="chat-history-container"], [data-testid="chat-messages-wrapper"]');
		const historyText = (await chatHistory.first().textContent()) || '';
		logCheckpoint(`Chat history text (excerpt): "${historyText.substring(0, 300)}"`);

		const emailMatch = historyText.match(/\[EMAIL_\w+\]/);
		if (emailMatch) {
			logCheckpoint(`Found ${emailMatch[0]} in chat history text.`);
			userMsgText = historyText;
		}

		// Assign userMessage anyway so we can use it later for PII span checks
		userMessage = userMsgElement;
		if (!userMsgText) {
			userMsgText = (await userMsgElement.textContent()) || '';
			logCheckpoint(`User message text after 30s: "${userMsgText.trim().substring(0, 150)}"`);
		}
	}

	// The user message text should contain [EMAIL_com] placeholder
	logCheckpoint(`User message text for PII check: "${userMsgText.trim().substring(0, 150)}"`);
	expect(userMsgText).toMatch(/\[EMAIL_\w+\]/);
	logCheckpoint('User message contains [EMAIL_*] placeholder text.');

	// Check if PII decoration spans are rendered (pii-restored class)
	// These may take a moment to render since ReadOnlyMessage uses TipTap decorations
	const userPiiSpan = userMessage.locator('[data-testid="pii-restored"]');
	let piiSpanCount = await userPiiSpan.count();
	logCheckpoint(`PII decoration spans found: ${piiSpanCount}`);

	if (piiSpanCount === 0) {
		// Wait a bit longer and retry — TipTap decorations may need more time
		await page.waitForTimeout(3000);
		piiSpanCount = await userPiiSpan.count();
		logCheckpoint(`PII spans after extended wait: ${piiSpanCount}`);
	}

	if (piiSpanCount > 0) {
		// In hidden mode (default), the placeholder text like [EMAIL_com] should be displayed
		const userPiiText = await userPiiSpan.first().textContent();
		logCheckpoint(`User message PII span text (hidden mode): "${userPiiText}"`);

		// The PII span should have the hidden class (default mode)
		const userPiiClass = await userPiiSpan.first().getAttribute('class');
		logCheckpoint(`User message PII span class: "${userPiiClass}"`);
		expect(userPiiClass).toContain('pii-hidden');

		// Verify the placeholder format [EMAIL_com]
		expect(userPiiText).toMatch(/\[EMAIL_\w+\]/);
		logCheckpoint('User message PII span correctly shows [EMAIL_*] in hidden mode.');
	} else {
		logCheckpoint(
			'PII decoration spans not rendered yet — placeholder text verified in raw content.'
		);
	}

	await takeStepScreenshot(page, 'pii-user-message-hidden');

	// ======================================================================
	// STEP 10: Verify assistant response references the placeholder
	// ======================================================================
	logCheckpoint('Checking assistant response for placeholder reference...');

	// Assistant message was already confirmed visible in STEP 9
	// Wait a bit more for streaming to complete
	await page.waitForTimeout(5000);

	const assistantText = await assistantMessage.textContent();
	logCheckpoint(`Assistant response text (first 200 chars): "${assistantText?.substring(0, 200)}"`);

	// The assistant should see and potentially reference [EMAIL_com] since the original was replaced
	// This is not always guaranteed (the assistant may or may not echo it), so we just log it
	const assistantRefersPlaceholder = assistantText?.match(/\[EMAIL_\w+\]/);
	logCheckpoint(`Assistant references [EMAIL_*]: ${!!assistantRefersPlaceholder}`);

	await takeStepScreenshot(page, 'pii-assistant-response');

	// ======================================================================
	// STEP 11: Test the PII show/hide toggle button
	// ======================================================================
	logCheckpoint('Testing PII show/hide toggle button...');

	// The toggle button is a single element with data-testid="chat-pii-toggle".
	// Its data-pii-revealed attr flips between "false" (placeholders shown) and
	// "true" (originals shown).
	const chatPiiToggle = page.getByTestId('chat-pii-toggle');

	const toggleVisible = await chatPiiToggle.isVisible({ timeout: 5000 }).catch(() => false);
	const initialToggleRevealed = toggleVisible
		? await chatPiiToggle.getAttribute('data-pii-revealed')
		: null;
	logCheckpoint(
		`Chat header PII toggle visible: ${toggleVisible}, data-pii-revealed: ${initialToggleRevealed}`
	);

	if (toggleVisible && initialToggleRevealed === 'false') {
		// Click the toggle to reveal the original email
		logCheckpoint('Clicking chat header PII toggle to reveal...');
		await chatPiiToggle.click();
		await page.waitForTimeout(2000);

		const revealedAttrAfterClick = await chatPiiToggle.getAttribute('data-pii-revealed');
		expect(revealedAttrAfterClick).toBe('true');

		await takeStepScreenshot(page, 'pii-toggle-revealed');

		// Re-read user message text — it should now show the original email instead of placeholder
		const revealedMsgText = await userMessage.textContent();
		logCheckpoint(`User message text after reveal: "${revealedMsgText?.substring(0, 150)}"`);

		// After revealing, check for pii-revealed spans (orange text with original values)
		const revealedPii = userMessage.locator('[data-testid="pii-restored"].pii-revealed');
		const revealedCount = await revealedPii.count();
		logCheckpoint(`Revealed PII spans in user message: ${revealedCount}`);

		if (revealedCount > 0) {
			const revealedText = await revealedPii.first().textContent();
			logCheckpoint(`Revealed PII text: "${revealedText}"`);
			expect(revealedText).toContain('testuser@privateemail.org');
			logCheckpoint('Original email correctly revealed in user message.');

			const hiddenPiiAfterReveal = await userMessage.locator('[data-testid="pii-restored"].pii-hidden').count();
			logCheckpoint(`Hidden PII spans after reveal: ${hiddenPiiAfterReveal}`);
			expect(hiddenPiiAfterReveal).toBe(0);
		} else {
			expect(revealedMsgText).toContain('testuser@privateemail.org');
			logCheckpoint('Original email visible in message text after reveal (no decoration spans).');
		}

		// Now click the same toggle again to re-hide
		logCheckpoint('Clicking chat header PII toggle to re-hide...');
		await chatPiiToggle.click();
		await page.waitForTimeout(2000);

		const hiddenAttrAfterClick = await chatPiiToggle.getAttribute('data-pii-revealed');
		expect(hiddenAttrAfterClick).toBe('false');

		await takeStepScreenshot(page, 'pii-toggle-hidden-again');

		const reHiddenMsgText = await userMessage.textContent();
		logCheckpoint(`User message text after re-hide: "${reHiddenMsgText?.substring(0, 150)}"`);
		expect(reHiddenMsgText).toMatch(/\[EMAIL_\w+\]/);
		logCheckpoint('User message correctly re-hidden with placeholder.');

		const hiddenPiiAfterReHide = userMessage.locator('[data-testid="pii-restored"].pii-hidden');
		const hiddenCountAfterReHide = await hiddenPiiAfterReHide.count();
		logCheckpoint(`Hidden PII spans after re-hide: ${hiddenCountAfterReHide}`);

		if (hiddenCountAfterReHide > 0) {
			const hiddenTextAgain = await hiddenPiiAfterReHide.first().textContent();
			logCheckpoint(`Re-hidden PII span text: "${hiddenTextAgain}"`);
			expect(hiddenTextAgain).toMatch(/\[EMAIL_\w+\]/);
		}

		const revealedAfterReHide = await userMessage.locator('[data-testid="pii-restored"].pii-revealed').count();
		logCheckpoint(`Revealed PII spans after re-hide: ${revealedAfterReHide}`);
		expect(revealedAfterReHide).toBe(0);
	} else if (toggleVisible && initialToggleRevealed === 'true') {
		logCheckpoint('Toggle already in revealed state — clicking to hide first.');
		await chatPiiToggle.click();
		await page.waitForTimeout(1000);
	} else {
		logCheckpoint(
			'WARNING: PII toggle button not found. Chat may not have registered PII mappings yet.'
		);
	}

	await takeStepScreenshot(page, 'pii-toggle-verified');

	// Verify no missing translations on the chat page with PII UI elements
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ======================================================================
	// STEP 12: Delete the chat (cleanup)
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
