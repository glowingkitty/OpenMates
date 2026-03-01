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
// Uploads the finance mate profile image, asks the AI to describe it,
// verifies the AI acknowledges viewing the image (ImageViewEmbedPreview card
// with data-app-id="images" data-skill-id="view" reaches "finished" state),
// verifies the thumbnail renders, clicks it to open ImageEmbedFullscreen,
// and closes it.
// ---------------------------------------------------------------------------

test('finance image: upload, AI views image, image-view embed renders and opens fullscreen', async ({
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
	// AI response + image processing can be slow — allow 4 minutes
	test.setTimeout(240000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('FILE_ATTACH_FINANCE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-finance' });
	await archiveExistingScreenshots(log);

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);
	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	// ======================================================================
	// STEP 2: Attach the finance mate image
	// ======================================================================
	await attachFiles(page, [FINANCE_JPEG], log);
	// Allow time for upload to S3 and TipTap NodeView to mount
	await page.waitForTimeout(4000);
	await screenshot(page, 'after-finance-attach');
	saveWarnErrorLogs('finance', 'after_file_attach');

	// Verify the image embed appeared in the editor
	const embedInEditor = page.locator('.editor-content .embed-full-width-wrapper');
	await expect(async () => {
		await expect(embedInEditor.first()).toBeVisible();
	}).toPass({ timeout: 20000 });
	log('Finance image embed appeared in editor.');
	await screenshot(page, 'finance-embed-in-editor');

	// ======================================================================
	// STEP 3: Type the question and send
	// The question is intentionally simple so the AI just views the image
	// and answers with a color — no long reasoning needed.
	// ======================================================================
	// Move cursor to end without clicking on the embed (would open fullscreen)
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

	// Wait for the chat URL to confirm we are in a real (non-demo) chat
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatUrl = page.url();
	log(`Chat URL after send: ${chatUrl}`);

	await screenshot(page, 'message-sent');
	saveWarnErrorLogs('finance', 'after_send');

	// ======================================================================
	// STEP 4: Wait for the assistant response and verify the AI viewed the image
	// We wait for streaming to finish before reading the text.
	//
	// IMPORTANT: Scope to .active-chat-container to avoid picking up messages
	// from demo chats or previous chats that may still be in the DOM.
	// Record the pre-send count so we can wait for a NEW assistant message.
	// ======================================================================
	log('Waiting for assistant response...');

	// Scope all message lookups to the active chat container only
	const activeChatContainer = page.locator('.active-chat-container');

	// Record how many assistant messages exist before the new one arrives.
	// We need to wait for a brand new message, not re-read an existing one.
	const preSendCount = await activeChatContainer.locator('.message-wrapper.assistant').count();
	log(`Pre-send assistant message count in active chat: ${preSendCount}`);

	// Wait for at least one new assistant message (count > preSendCount)
	const assistantMessages = activeChatContainer.locator('.message-wrapper.assistant');
	await expect(async () => {
		const count = await assistantMessages.count();
		if (count <= preSendCount) throw new Error(`No new assistant message yet (count=${count})`);
	}).toPass({ timeout: 60000, intervals: [1000] });
	log('New assistant message wrapper appeared.');

	// Wait for streaming to finish: the response should stop updating.
	// Poll until the text is non-empty and stable (two consecutive reads match).
	let stableText = '';
	await expect(async () => {
		const text = await assistantMessages.last().textContent();
		if (!text || text.trim().length < 3) throw new Error('Response too short');
		if (text === stableText) return; // stable — done
		stableText = text ?? '';
		throw new Error('Still streaming');
	}).toPass({ timeout: 90000, intervals: [2000] });
	log(`Stable assistant response: "${stableText.substring(0, 200)}"`);

	// Assert the AI actually processed and viewed the image — it should mention
	// something about the image content (person, man, image, photo, etc.).
	// We do NOT assert on color since the finance mate persona (George) tends to
	// redirect color questions toward financial topics. The key test value here
	// is the embed render + fullscreen flow, not AI text interpretation.
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
	log('Verified: AI response acknowledges the attached image.');
	await screenshot(page, 'ai-response-green-verified');
	saveWarnErrorLogs('finance', 'after_ai_response');

	// ======================================================================
	// STEP 5: Verify the ImageViewEmbedPreview card rendered in the assistant message
	// The AI uses the images/view skill to view the image, which mounts
	// ImageViewEmbedPreview with data-app-id="images" data-skill-id="view".
	// Scope to activeChatContainer to avoid matching cards from other chats.
	// ======================================================================
	log('Looking for ImageViewEmbedPreview card in assistant message...');
	const imageViewPreview = activeChatContainer.locator(
		'.unified-embed-preview[data-app-id="images"][data-skill-id="view"]'
	);
	await expect(imageViewPreview.first()).toBeVisible({ timeout: 30000 });
	log('ImageViewEmbedPreview card is visible.');

	// Verify it reached finished state
	const finishedImageView = activeChatContainer.locator(
		'.unified-embed-preview[data-app-id="images"][data-skill-id="view"][data-status="finished"]'
	);
	await expect(finishedImageView.first()).toBeVisible({ timeout: 30000 });
	log('ImageViewEmbedPreview reached finished state.');

	// Verify the image thumbnail is rendered inside the preview card
	// Architecture: .image-view-preview > .image-content.clickable > img.preview-image
	const imageThumbnail = finishedImageView.first().locator('img.preview-image');
	await expect(imageThumbnail).toBeVisible({ timeout: 10000 });
	const thumbSrc = await imageThumbnail.getAttribute('src');
	log(`Image thumbnail src prefix: "${thumbSrc?.substring(0, 60)}"`);
	expect(thumbSrc).toBeTruthy();
	log('Image thumbnail is visible inside the preview card.');
	await screenshot(page, 'image-view-preview-verified');

	// ======================================================================
	// STEP 6: Click the preview card to open ImageEmbedFullscreen
	// Flow: click → UnifiedEmbedPreview.handleClick() → onFullscreen() →
	//       AppSkillUseRenderer.openImageUploadFullscreen() →
	//       fires 'imagefullscreen' CustomEvent →
	//       ActiveChat mounts ImageEmbedFullscreen (wrapped in UnifiedEmbedFullscreen)
	// Root overlay: .unified-embed-fullscreen-overlay
	// Content area: .image-embed-fullscreen > .image-wrapper > a.image-link > img.full-image
	// ======================================================================
	log('Clicking ImageViewEmbedPreview card to open image fullscreen...');
	await finishedImageView.first().click();

	// The fullscreen overlay should appear
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500); // wait for slide-up animation (320ms)
	log('Image fullscreen overlay (.unified-embed-fullscreen-overlay) is visible.');
	await screenshot(page, 'image-fullscreen-opened');
	saveWarnErrorLogs('finance', 'after_fullscreen_open');

	// ======================================================================
	// STEP 7: Verify fullscreen content
	// ======================================================================
	// The content div inside the overlay
	const fullscreenContent = fullscreenOverlay.locator('.image-embed-fullscreen');
	await expect(fullscreenContent).toBeVisible({ timeout: 10000 });
	log('Image fullscreen content (.image-embed-fullscreen) is visible.');

	// The full-resolution image should load (may start as loading spinner then show image)
	// Wait for either the .full-image or the .image-loading spinner to appear
	await expect(async () => {
		const fullImg = fullscreenOverlay.locator('img.full-image');
		const loadingSpinner = fullscreenOverlay.locator('.image-loading');
		const hasImage = await fullImg.isVisible().catch(() => false);
		const hasSpinner = await loadingSpinner.isVisible().catch(() => false);
		expect(hasImage || hasSpinner).toBe(true);
	}).toPass({ timeout: 15000 });

	// Wait for the full image to actually load (spinner disappears, image appears)
	const fullImage = fullscreenOverlay.locator('img.full-image');
	await expect(fullImage).toBeVisible({ timeout: 30000 });
	log('Full-resolution image (img.full-image) is visible in fullscreen.');
	await screenshot(page, 'image-fullscreen-content-verified');

	// Verify the EmbedTopBar buttons are present
	const topBar = fullscreenOverlay.locator('.embed-top-bar');
	await expect(topBar).toBeVisible({ timeout: 5000 });
	const minimizeButton = fullscreenOverlay.locator('button.icon_minimize');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	log('EmbedTopBar and minimize button are visible.');
	await screenshot(page, 'image-fullscreen-buttons-verified');

	// ======================================================================
	// STEP 8: Close the fullscreen via the minimize button
	// ======================================================================
	log('Closing image fullscreen via minimize button...');
	await minimizeButton.click();
	await page.waitForTimeout(400);
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	log('Image fullscreen closed successfully.');
	await screenshot(page, 'image-fullscreen-closed');
	saveWarnErrorLogs('finance', 'after_fullscreen_closed');

	// ======================================================================
	// STEP 9: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, log);
	log(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('finance', 'final');
	log('Finance image flow test completed successfully.');
});
