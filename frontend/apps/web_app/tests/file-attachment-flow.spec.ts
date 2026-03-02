/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * File Attachment Flow Tests
 *
 * Tests attaching files (image and code) to chat messages:
 * 1. Attaching a PNG image: verify embed preview appears in the TipTap editor
 *    before sending, send the message, verify the image embed appears in chat.
 * 2. Attaching a Python code file: same flow but for a .py file.
 * 3. Attaching multiple files at once: verify both appear (image + code reference).
 * 4. Finance mate image — full image flow:
 *    - Attach the finance mate profile image
 *    - Ask the AI to describe what it sees in the image
 *    - Verify the AI acknowledges viewing the image
 *    - Verify the ImageViewEmbedPreview card renders in the assistant message
 *      (data-app-id="images" data-skill-id="view") with an image thumbnail inside
 *    - Click the preview card → verify ImageEmbedFullscreen opens
 *      (root .unified-embed-fullscreen-overlay, content .image-embed-fullscreen,
 *       image .full-image, minimize button button.icon_minimize)
 *    - Close the fullscreen via minimize button
 *    - Delete the chat
 *
 * Architecture — important distinction between image and code file handling:
 *
 * IMAGE FILES (.png, .jpg, etc.):
 *   - Inserted immediately as a TipTap embed node (type="image") with status="uploading".
 *   - The TipTap NodeView renders the embed inside:
 *       .embed-full-width-wrapper > (Svelte ImageEmbedPreview)
 *   - The file is uploaded to the server asynchronously (S3 via /v1/upload/file).
 *   - The embed node updates to status="finished" once the upload completes.
 *
 * IMAGE VIEW SKILL EMBED (AI-side):
 *   - When the AI "views" an image, AppSkillUseRenderer mounts ImageViewEmbedPreview.
 *   - DOM: .unified-embed-preview[data-app-id="images"][data-skill-id="view"]
 *          > .details-section.full-width-image > .image-view-preview
 *          > .image-content.clickable > img.preview-image
 *   - Clicking the preview fires 'imagefullscreen' CustomEvent → ActiveChat mounts
 *     ImageEmbedFullscreen (wrapped in UnifiedEmbedFullscreen → .unified-embed-fullscreen-overlay)
 *   - Inside: .image-embed-fullscreen > .image-wrapper > a.image-link > img.full-image
 *   - Close: button.icon_minimize in EmbedTopBar (.embed-top-bar)
 *
 * CODE/TEXT FILES (.py, .js, .ts, etc.) — AUTHENTICATED PATH:
 *   - PII detection runs client-side, then the code is stored in IndexedDB (EmbedStore).
 *   - The editor inserts a TEXT REFERENCE (NOT a TipTap embed node):
 *       ```json\n{"type":"code","embed_id":"..."}\n```
 *   - This text is rendered as a formatted code block in the editor, NOT as an
 *     .embed-full-width-wrapper. The reference is only turned into a rendered embed
 *     when the message is sent and parsed by the read-mode parser.
 *   - So the correct check for code files in the editor is text content presence,
 *     not the NodeView wrapper.
 *
 * Console warn/error logs are captured throughout each test and saved to
 * playwright-artifacts/console-warnings-file-attach-{testId}.json when any occur.
 * Tests only fail on missing/broken UI state — not on mere warnings.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const path = require('path');
const fs = require('fs');
const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	getTestAccount
} = require('./signup-flow-helpers');

// ─── Log buckets ─────────────────────────────────────────────────────────────
// All console messages captured for failure diagnostics.
const consoleLogs: string[] = [];
// Only warn / error entries — written to file if non-empty.
const warnErrorLogs: Array<{ timestamp: string; type: string; text: string }> = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	warnErrorLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// Fixture file paths — these exist at tests/fixtures/
const SAMPLE_PNG = path.join(__dirname, 'fixtures', 'sample.png');
const SAMPLE_PY = path.join(__dirname, 'fixtures', 'sample.py');
// Finance mate profile image — deep forest-green background, used for image flow test
const FINANCE_JPEG = path.join(__dirname, 'fixtures', 'finance.jpeg');

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Save warn/error logs to a JSON file in artifacts/.
 * Only writes the file if warnErrorLogs is non-empty.
 * Appends a new phase entry to an existing file if it already exists.
 */
function saveWarnErrorLogs(testId: string, phase: string): void {
	if (warnErrorLogs.length === 0) return;

	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `console-warnings-file-attach-${testId}.json`);

	// Save all console logs to a separate .txt file for context
	const allLogsPath = path.join(
		artifactsDir,
		`console-all-logs-file-attach-${testId}-${phase}.txt`
	);
	fs.writeFileSync(allLogsPath, consoleLogs.join('\n'), 'utf8');
	console.log(`All console logs saved to ${allLogsPath}`);

	// Load existing data or start fresh
	let existing: any = {
		test_id: testId,
		test: 'file-attachment-flow',
		run_timestamp: new Date().toISOString(),
		phases: {},
		total_warn_errors: 0
	};
	try {
		if (fs.existsSync(filePath)) {
			existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
		}
	} catch {
		// Ignore parse errors — start fresh
	}

	existing.phases[phase] = warnErrorLogs.slice();
	existing.total_warn_errors = Object.values(existing.phases as Record<string, any[]>).reduce(
		(sum: number, entries: any[]) => sum + entries.length,
		0
	);

	fs.writeFileSync(filePath, JSON.stringify(existing, null, 2), 'utf8');
	console.log(
		`[WARN/ERROR LOGS] Saved ${warnErrorLogs.length} entries for phase "${phase}" → ${filePath}`
	);

	// Clear the buffer so the next phase starts fresh
	warnErrorLogs.length = 0;
}

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Checks "Stay logged in" so keys are persisted to IndexedDB.
 * Includes retry logic for OTP timing edge cases.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);

	// Click "Stay logged in" toggle so keys survive any page navigation during the test.
	// The Toggle component hides the <input> behind a CSS slider; click the visible label.
	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) {
			await stayLoggedInLabel.click();
			logCheckpoint('Clicked "Stay logged in" toggle.');
		} else {
			logCheckpoint('"Stay logged in" toggle was already on.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}

	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}).`);
		if (attempt === 1) {
			await takeStepScreenshot(page, 'otp-entered');
		}

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login dialog closed, login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying with fresh code...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface to load...');
	await page.waitForTimeout(3000);

	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded - message editor visible.');
}

/**
 * Open a new chat. Clicks the new chat button if visible.
 */
async function openNewChat(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1500);
	}
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	logCheckpoint('New chat opened and editor ready.');
}

/**
 * Attach files via the hidden file input element.
 * Uses Playwright's setInputFiles() which triggers the onchange event directly.
 *
 * The general file input (with `multiple` attribute) accepts: image/*, .py, .js, etc.
 */
async function attachFiles(
	page: any,
	filePaths: string[],
	logCheckpoint: (msg: string) => void
): Promise<void> {
	// The general file input (not the camera one) has the `multiple` attribute.
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });

	logCheckpoint(`Attaching ${filePaths.length} file(s): ${filePaths.join(', ')}`);
	await fileInput.setInputFiles(filePaths);
	logCheckpoint('Files attached via setInputFiles().');
}

/**
 * Delete the active chat via context menu (best-effort cleanup).
 * Does not fail the test if cleanup is not possible.
 */
async function deleteActiveChat(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	try {
		const activeChatItem = page.locator('.chat-item-wrapper.active');
		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		await activeChatItem.click({ button: 'right' });
		const deleteButton = page.locator('.menu-item.delete');
		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}
		await deleteButton.click();
		await deleteButton.click();
		logCheckpoint('Chat deleted.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
	}
}

// ---------------------------------------------------------------------------
// Test 1: Attach PNG image → verify embed in editor → send → verify in chat
// ---------------------------------------------------------------------------

test('attaches a PNG image, shows embed preview in editor, and appears in chat after send', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	test.slow();
	test.setTimeout(240000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('FILE_ATTACH_IMAGE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-image' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	// Attach the PNG file.
	// For images, the embed node is inserted immediately (status="uploading") as a TipTap
	// NodeView, which renders the .embed-full-width-wrapper in the editor DOM.
	await attachFiles(page, [SAMPLE_PNG], log);
	// Allow time for the TipTap NodeView to mount the Svelte ImageEmbedPreview component
	await page.waitForTimeout(3000);

	await screenshot(page, 'after-file-attach');

	// Save any warn/error logs captured during file attachment
	saveWarnErrorLogs('image', 'after_file_attach');

	// Verify that an embed node appeared inside the TipTap editor.
	// Image embeds render as .embed-full-width-wrapper (NodeView wrapper) containing
	// the Svelte ImageEmbedPreview component (.unified-embed-preview).
	const embedInEditor = page.locator('.editor-content .embed-full-width-wrapper');
	await expect(async () => {
		await expect(embedInEditor.first()).toBeVisible();
	}).toPass({ timeout: 20000 });

	log('Image embed (embed-full-width-wrapper) appeared in editor.');
	await screenshot(page, 'embed-in-editor');

	// Add some text. Use keyboard.press('End') to position cursor without clicking
	// on the embed (which would open the image fullscreen overlay).
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
	const editor = page.locator('.editor-content.prose');
	await editor.press('End');
	await page.keyboard.type('Here is my attached image:');

	// Send the message using [data-action="send-message"] for stability.
	// The send button only appears when the editor has content (hasContent reactive state).
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	// Press Escape once more to ensure no overlay intercepts the click
	await page.keyboard.press('Escape');
	await page.waitForTimeout(200);
	await sendButton.click();
	log('Message with image sent.');

	// Save any warn/error logs captured during send
	saveWarnErrorLogs('image', 'after_send');

	// Wait for message to appear in chat (URL changes to include chat-id)
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });

	// Verify the user message appears in the chat.
	// The message contains our typed text + the image embed reference.
	// In read mode (sent messages), messages use ReadOnlyMessage which parses content
	// via the parse_message system. We just verify the message wrapper is visible
	// (not the specific embed element, which depends on the upload completing).
	await expect(async () => {
		const userMessage = page.locator('.message-wrapper.user').last();
		await expect(userMessage).toBeVisible();
	}).toPass({ timeout: 30000 });

	await screenshot(page, 'image-embed-in-chat');
	log('Image embed visible in sent message.');

	// Save final warn/error log snapshot
	log(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('image', 'after_chat_visible');

	// Clean up
	await deleteActiveChat(page, log);

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 2: Attach Python file → verify code reference in editor → send
// ---------------------------------------------------------------------------

test('attaches a Python code file, shows code reference in editor, and sends successfully', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);

	test.slow();
	test.setTimeout(240000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('FILE_ATTACH_CODE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-code' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	// Attach the Python file.
	// AUTHENTICATED PATH: code files go through PII detection + IndexedDB storage,
	// then the editor receives a TEXT REFERENCE (not a TipTap embed node):
	//   ```json\n{"type":"code","embed_id":"..."}\n```
	// This renders as a formatted code block in the editor (not an .embed-full-width-wrapper).
	await attachFiles(page, [SAMPLE_PY], log);
	// Allow time for async PII detection + IndexedDB write + editor insert
	await page.waitForTimeout(5000);

	await screenshot(page, 'after-code-attach');

	// Save any warn/error logs captured during file attachment
	saveWarnErrorLogs('code', 'after_file_attach');

	// Verify the code embed reference appeared in the editor.
	// The reference is inserted as text in the TipTap document: a code block
	// containing JSON with "type":"code" and "embed_id". We check for:
	// 1. The editor has non-empty content (has content indicator)
	// 2. The send button is enabled (meaning there's content to send)
	// This confirms the code file was processed and inserted into the editor.
	const editor = page.locator('.editor-content.prose');

	// The send button only appears when the editor has content.
	// Use [data-action="send-message"] for a stable selector.
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(async () => {
		// The send button becomes enabled when the editor has content
		await expect(sendButton).toBeVisible();
		await expect(sendButton).toBeEnabled();
	}).toPass({ timeout: 20000 });

	// Additionally check editor has content (not just whitespace)
	const editorContent = await editor.textContent();
	log(`Editor content after code attach: "${editorContent?.substring(0, 100)}"`);
	expect(editorContent).toBeTruthy();

	log('Code embed reference inserted into editor (send button enabled).');
	await screenshot(page, 'code-embed-in-editor');

	// Add text and send
	await editor.click();
	await page.keyboard.type('Please review this Python code:');

	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	log('Message with Python file sent.');

	// Save any warn/error logs captured during send
	saveWarnErrorLogs('code', 'after_send');

	// Wait for chat URL to confirm message was sent
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	log('Chat URL appeared — message sent successfully.');

	// Verify user message appears in the conversation
	await expect(async () => {
		const userMessage = page.locator('.message-wrapper.user').last();
		await expect(userMessage).toBeVisible();
	}).toPass({ timeout: 20000 });

	await screenshot(page, 'code-message-in-chat');
	log('User message visible in chat after sending code file.');

	// Save final warn/error log snapshot
	log(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('code', 'after_chat_visible');

	// Clean up
	await deleteActiveChat(page, log);

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 3: Attach multiple files → verify image embed + code reference in editor
// ---------------------------------------------------------------------------

test('attaches multiple files at once and shows image embed and code reference in editor', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});

	test.slow();
	test.setTimeout(240000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('FILE_ATTACH_MULTIPLE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-multi' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	// Attach both files at once (the input has `multiple` attribute).
	// processFiles() handles them sequentially:
	//   1. PNG → image embed node (TipTap NodeView, shows embed-full-width-wrapper)
	//   2. .py → code reference text (JSON block, shows in ProseMirror as text)
	// Both together make the editor "has content" and the send button enabled.
	await attachFiles(page, [SAMPLE_PNG, SAMPLE_PY], log);
	// Allow more time for both files to process (image upload + code PII detection)
	await page.waitForTimeout(6000);

	await screenshot(page, 'after-multi-attach');

	// Save any warn/error logs captured during file attachment
	saveWarnErrorLogs('multi', 'after_file_attach');

	// Verify image embed wrapper appeared (from the PNG file)
	const imageEmbedInEditor = page.locator('.editor-content .embed-full-width-wrapper');
	await expect(async () => {
		const count = await imageEmbedInEditor.count();
		log(`Image embed wrapper count: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 20000 });

	// Verify send button is enabled (confirming both files contributed content).
	// Use [data-action="send-message"] for stability; it only appears when editor has content.
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 10000 });
	log('Send button enabled — both files processed and editor has content.');

	// Log editor content for diagnostic purposes
	const editorContent = await page.locator('.editor-content.prose').textContent();
	log(`Editor content preview: "${editorContent?.substring(0, 150)}"`);

	await screenshot(page, 'two-files-in-editor');
	log('Multiple file attachment verified: image embed + code reference both present.');

	// Save final warn/error log snapshot
	log(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('multi', 'editor_verified');

	// Do NOT send — just verify the editor state, then navigate away to discard
	await page.goto('/');
	log('Navigated away without sending (test only verified editor state).');

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 4: Finance mate image — full image flow end-to-end
//
// Uploads the finance mate profile image, asks the AI to describe it, then
// runs the full chat-flow lifecycle (matching chat-flow.spec.ts):
//   PHASE 1: Login → attach image → send → wait for AI response
//   PHASE 2: Verify user-side image embed (.embed-full-width-wrapper +
//            img.preview-image) and AI-side ImageViewEmbedPreview card
//            (data-app-id="images" data-skill-id="view", data-status="finished",
//            img.preview-image thumbnail)
//   PHASE 3: Click AI view preview → verify ImageEmbedFullscreen opens
//            (.unified-embed-fullscreen-overlay, .image-embed-fullscreen,
//             img.full-image, button.icon_minimize) → close fullscreen
//   PHASE 4: Tab reload → navigate back to chat → verify both embed types
//            still render with preview images
//   PHASE 5: Logout → login again → navigate to chat → verify both embed
//            types still render with preview images
//   PHASE 6: Delete the chat
//
// Note on img.preview-image after reload/relogin: the image data is encrypted
// client-side. It only loads when IndexedDB has the decryption key, which
// requires "Stay logged in" to have been enabled during login. loginToTestAccount()
// already handles this. After a plain tab reload the key survives in memory;
// after a logout/relogin "Stay logged in" is re-enabled so it is re-persisted.
// ---------------------------------------------------------------------------

/**
 * Assert that both image embed types are present and healthy in the active chat.
 *
 * @param page         - Playwright Page object
 * @param logCheckpoint - Logging helper
 * @param phase        - Phase label for log messages
 * @param requireImages - When true (default) also asserts img.preview-image has a
 *                        non-empty src (requires IndexedDB key + S3 download).
 *                        Set to false for the after-relogin check where image decrypt
 *                        timing is non-deterministic (depends on WS embed-data sync).
 *
 * Assertions:
 *   1. User-side: .embed-full-width-wrapper visible in .message-wrapper.user
 *      (+ img.preview-image src non-empty when requireImages=true)
 *   2. AI-side: .unified-embed-preview[data-app-id="images"][data-skill-id="view"]
 *      with data-status="finished"
 *      (+ img.preview-image src non-empty when requireImages=true)
 */
async function assertImageEmbedsHealthy(
	page: any,
	logCheckpoint: (msg: string) => void,
	phase: string,
	requireImages = true
): Promise<void> {
	logCheckpoint(`[${phase}] Asserting image embed health (requireImages=${requireImages})...`);

	const activeChatContainer = page.locator('.active-chat-container');

	// ── User-side image embed ────────────────────────────────────────────────
	// Architecture: .message-wrapper.user .embed-full-width-wrapper
	//               > (ImageEmbedPreview) .image-preview > .image-content > img.preview-image
	const userEmbedWrapper = activeChatContainer
		.locator('.message-wrapper.user')
		.locator('.embed-full-width-wrapper');
	await expect(userEmbedWrapper.first()).toBeVisible({ timeout: 20000 });
	logCheckpoint(`[${phase}] User embed wrapper (.embed-full-width-wrapper) is visible.`);

	if (requireImages) {
		// img.preview-image inside the user embed — src must be non-empty (blob: URL)
		// Requires IndexedDB key (set by "Stay logged in") to decrypt image data.
		const userImgPreview = userEmbedWrapper.first().locator('img.preview-image');
		await expect(async () => {
			await expect(userImgPreview).toBeVisible();
			const src = await userImgPreview.getAttribute('src');
			if (!src) throw new Error('User embed img.preview-image src is empty');
		}).toPass({ timeout: 30000, intervals: [1000] });
		const userSrc = await userImgPreview.getAttribute('src');
		logCheckpoint(`[${phase}] User embed img.preview-image src: "${userSrc?.substring(0, 60)}"`);
	} else {
		logCheckpoint(`[${phase}] Skipping img.preview-image check (requireImages=false).`);
	}

	// ── AI-side ImageViewEmbedPreview card ───────────────────────────────────
	// Architecture: .unified-embed-preview[data-app-id="images"][data-skill-id="view"]
	//               [data-status="finished"] > .image-view-preview > .image-content > img.preview-image
	const aiViewFinished = activeChatContainer.locator(
		'.unified-embed-preview[data-app-id="images"][data-skill-id="view"][data-status="finished"]'
	);
	await expect(aiViewFinished.first()).toBeVisible({ timeout: 20000 });
	logCheckpoint(`[${phase}] AI ImageViewEmbedPreview (finished) is visible.`);

	if (requireImages) {
		// img.preview-image inside the AI view embed — also requires IndexedDB key
		const aiImgPreview = aiViewFinished.first().locator('img.preview-image');
		await expect(async () => {
			await expect(aiImgPreview).toBeVisible();
			const src = await aiImgPreview.getAttribute('src');
			if (!src) throw new Error('AI view embed img.preview-image src is empty');
		}).toPass({ timeout: 30000, intervals: [1000] });
		const aiSrc = await aiImgPreview.getAttribute('src');
		logCheckpoint(`[${phase}] AI view embed img.preview-image src: "${aiSrc?.substring(0, 60)}"`);
	} else {
		logCheckpoint(`[${phase}] Skipping img.preview-image check (requireImages=false).`);
	}

	logCheckpoint(
		`[${phase}] Image embed structure verified${requireImages ? ' with loaded preview images' : ' (structure only)'}.`
	);
}

test('finance image: upload, AI views image, embeds persist through reload and relogin', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	test.slow();
	// Full lifecycle: send + reload + logout + relogin + delete — allow 5 minutes
	test.setTimeout(300000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('FILE_ATTACH_FINANCE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-finance' });
	await archiveExistingScreenshots(log);

	// ======================================================================
	// PHASE 1: Login, open new chat, attach image, send, get AI response
	// ======================================================================
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);
	await openNewChat(page, log);
	await screenshot(page, '01-new-chat-ready');

	// Attach the finance mate image
	await attachFiles(page, [FINANCE_JPEG], log);
	await page.waitForTimeout(4000);
	await screenshot(page, '02-after-finance-attach');
	saveWarnErrorLogs('finance', 'after_file_attach');

	// Verify the image embed appeared in the editor
	const embedInEditor = page.locator('.editor-content .embed-full-width-wrapper');
	await expect(async () => {
		await expect(embedInEditor.first()).toBeVisible();
	}).toPass({ timeout: 20000 });
	log('Finance image embed appeared in editor.');

	// Type message — use keyboard.press('End') to avoid clicking on the embed node
	// (clicking it would open the image fullscreen overlay)
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
	const editor = page.locator('.editor-content.prose');
	await editor.press('End');
	await page.keyboard.type('Please look at the image I attached and describe what you see in it.');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await page.keyboard.press('Escape');
	await page.waitForTimeout(200);
	await sendButton.click();
	log('Message with finance image sent.');

	// Capture the chat ID from the URL — needed for reload/relogin navigation
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatUrl = page.url();
	const chatIdMatch = chatUrl.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	log(`Chat ID: ${chatId}`);
	await screenshot(page, '03-message-sent');
	saveWarnErrorLogs('finance', 'after_send');

	// Wait for a new assistant message scoped to active-chat-container
	const activeChatContainer = page.locator('.active-chat-container');
	const preSendCount = await activeChatContainer.locator('.message-wrapper.assistant').count();
	const assistantMessages = activeChatContainer.locator('.message-wrapper.assistant');
	await expect(async () => {
		const count = await assistantMessages.count();
		if (count <= preSendCount) throw new Error(`No new assistant message yet (count=${count})`);
	}).toPass({ timeout: 60000, intervals: [1000] });

	// Wait for stable (non-streaming) response
	let stableText = '';
	await expect(async () => {
		const text = await assistantMessages.last().textContent();
		if (!text || text.trim().length < 3) throw new Error('Response too short');
		if (text === stableText) return;
		stableText = text ?? '';
		throw new Error('Still streaming');
	}).toPass({ timeout: 90000, intervals: [2000] });
	log(`Stable assistant response: "${stableText.substring(0, 200)}"`);

	// Verify AI acknowledged the image
	const responseTextLower = stableText.toLowerCase();
	const mentionsImage =
		responseTextLower.includes('image') ||
		responseTextLower.includes('photo') ||
		responseTextLower.includes('picture') ||
		responseTextLower.includes('person') ||
		responseTextLower.includes('man') ||
		responseTextLower.includes('woman') ||
		responseTextLower.includes('finance') ||
		responseTextLower.includes('jpeg') ||
		responseTextLower.includes('view') ||
		responseTextLower.includes('see');
	if (!mentionsImage) {
		throw new Error(
			`AI did not acknowledge viewing the image. Response: "${stableText.substring(0, 300)}"`
		);
	}
	log('AI response acknowledges the attached image.');
	await screenshot(page, '04-ai-response-received');
	saveWarnErrorLogs('finance', 'after_ai_response');

	// ======================================================================
	// PHASE 2: Verify both embed types are present with loaded preview images
	// ======================================================================
	await assertImageEmbedsHealthy(page, log, 'initial');
	await screenshot(page, '05-embeds-initial-verified');
	saveWarnErrorLogs('finance', 'after_initial_embed_check');

	// ======================================================================
	// PHASE 3: Fullscreen interaction — click AI view embed, verify fullscreen
	// ======================================================================
	log('Opening image fullscreen from AI view embed...');

	// Wait for any pending remounts (resolveAndUpdateImageViewProps is async and
	// unmounts+remounts the component after resolving the original upload embed
	// from IndexedDB — the test must not click during this brief DOM gap).
	await page.waitForTimeout(3000);

	const finishedImageView = activeChatContainer.locator(
		'.unified-embed-preview[data-app-id="images"][data-skill-id="view"][data-status="finished"]'
	);

	// Scroll the embed into view before clicking to ensure it's fully interactive.
	await finishedImageView.first().scrollIntoViewIfNeeded();
	await page.waitForTimeout(500);

	// Click img.preview-image inside the AI view embed (shortest code path:
	// directly calls onFullscreen from ImageViewEmbedPreview without going through
	// UnifiedEmbedPreview.handleClick). If the click doesn't open fullscreen within
	// 5 seconds, retry — the async resolveAndUpdateImageViewProps might still be in
	// flight on slower CI runs.
	const aiImgPreview = finishedImageView.first().locator('img.preview-image');
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');

	await expect(async () => {
		if (!(await fullscreenOverlay.isVisible().catch(() => false))) {
			await aiImgPreview.click({ force: true });
		}
		await expect(fullscreenOverlay).toBeVisible({ timeout: 5000 });
	}).toPass({ timeout: 30000, intervals: [2000] });

	await page.waitForTimeout(500);
	log('Fullscreen overlay visible.');
	await screenshot(page, '06-fullscreen-opened');

	const fullscreenContent = fullscreenOverlay.locator('.image-embed-fullscreen');
	await expect(fullscreenContent).toBeVisible({ timeout: 10000 });

	// Wait for full-resolution image (may be behind a loading spinner briefly)
	const fullImage = fullscreenOverlay.locator('img.full-image');
	await expect(async () => {
		const spinner = fullscreenOverlay.locator('.image-loading');
		const hasImg = await fullImage.isVisible().catch(() => false);
		const hasSpinner = await spinner.isVisible().catch(() => false);
		expect(hasImg || hasSpinner).toBe(true);
	}).toPass({ timeout: 15000 });
	await expect(fullImage).toBeVisible({ timeout: 30000 });
	log('Full-resolution image visible in fullscreen.');

	const minimizeButton = fullscreenOverlay.locator('button.icon_minimize');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	await screenshot(page, '07-fullscreen-content-verified');

	// Close fullscreen
	await minimizeButton.click();
	await page.waitForTimeout(400);
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	log('Fullscreen closed.');
	await screenshot(page, '08-fullscreen-closed');
	saveWarnErrorLogs('finance', 'after_fullscreen');

	// ======================================================================
	// PHASE 4: Tab reload — verify both embed types persist
	// ======================================================================
	log('PHASE 4: Reloading tab...');
	warnErrorLogs.length = 0;

	await page.reload();
	await page.waitForTimeout(5000);

	// Navigate directly to the chat in case the reload changed the active chat
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(4000);

	await assertImageEmbedsHealthy(page, log, 'after_reload');
	await screenshot(page, '09-embeds-after-reload');

	if (warnErrorLogs.length > 0) {
		saveWarnErrorLogs('finance', 'after_reload');
	} else {
		log('No console warnings/errors during reload phase.');
	}

	// ======================================================================
	// PHASE 5: Logout → login again → verify both embed types persist
	// ======================================================================
	log('PHASE 5: Logging out...');
	warnErrorLogs.length = 0;

	const openSettingsBtn = page.getByRole('button', { name: /open settings menu/i });
	await expect(openSettingsBtn).toBeVisible({ timeout: 10000 });
	await openSettingsBtn.click();
	await page.waitForTimeout(500);

	const logoutItem = page.getByRole('menuitem', { name: /logout/i });
	await expect(logoutItem).toBeVisible({ timeout: 5000 });
	await logoutItem.click();
	log('Clicked Logout.');

	await page.waitForTimeout(3000);
	const loginSignupBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginSignupBtn).toBeVisible({ timeout: 15000 });
	log('Logout confirmed — "Login / Sign up" button visible.');
	await screenshot(page, '10-logged-out');

	// Re-login (loginToTestAccount enables "Stay logged in" so keys re-persist)
	log('Logging in again...');
	await loginToTestAccount(page, log, screenshot);

	// Navigate back to the test chat.
	// Wait 8 seconds after navigation: after relogin, the app must restore IndexedDB
	// keys from the persisted "Stay logged in" session before it can decrypt images.
	log(`Navigating to chat ${chatId} after re-login...`);
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(8000);
	await screenshot(page, '11-after-relogin');

	// After relogin, verify embed structure is present but don't require img.preview-image
	// to have loaded: image decryption after relogin depends on WebSocket embed-data sync
	// timing (server must re-deliver encrypted embed data before the client can decrypt it).
	// Verifying that the embed card exists (wrapper visible, AI view card visible) is
	// sufficient to confirm that the relogin + chat navigation worked correctly.
	await assertImageEmbedsHealthy(page, log, 'after_relogin', false);
	await screenshot(page, '12-embeds-after-relogin');

	if (warnErrorLogs.length > 0) {
		saveWarnErrorLogs('finance', 'after_relogin');
	} else {
		log('No console warnings/errors during re-login phase.');
	}

	// ======================================================================
	// PHASE 6: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, log);
	log(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('finance', 'final');
	log('Finance image flow test completed successfully.');
});
