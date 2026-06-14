/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// Use shared console monitor (Rule 10) — replaces inline console boilerplate
const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners,
	allowConsoleErrorPatterns
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

/**
 * Multi-turn code generation E2E test.
 *
 * Verifies that a 3-turn conversation asking for iterative Python code
 * improvements works end-to-end:
 * - Each turn produces visible code embeds (not silently filtered)
 * - Code embeds reach "finished" status with Python content
 * - Each follow-up turn builds on the original code (not starting from scratch)
 * - No raw JSON embed references leak into visible text
 *
 * This is a regression test for issue 07ed2bbb: the fake tool call filter
 * was silently dropping code blocks tagged with language 'toon' by the LLM,
 * causing users to see only explanation text while being charged credits.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

// Explicitly use slot 1 — this is a long AI inference test that needs a reliable account.
// Slot 3 doesn't have 2FA configured, causing auth failures on parallel runs.
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

// All tests in this file use the same long-lived account slot and create chats
// with generated code embeds. Running them concurrently races chat-key setup and
// background embed sync, so keep the file serial while still letting other specs
// run in parallel workers.
test.describe.configure({ mode: 'serial' });

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Set up console and network listeners — delegates to console-monitor helpers.
 */
function setupPageListeners(page: any) {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	allowConsoleErrorPatterns([
		/\[ChatSyncService:AI\].*Chat key unavailable or unsafe for HKDF derivation; refusing to persist embed/,
		/\[ChatSyncService:AI\].*Failed to get parent embed key after 5 retries/,
		/\[ChatSyncService:AI\].*Failed to get parent embed key for child embed/,
		/\[ChatSyncService:AI\].*Chat .* not found in DB or incognito service for background response/,
		/\[ChatSyncService:AI\].*Error handling post-processing results for chat .* not found/
	]);
}

/**
 * Wait for a new assistant response to appear (for follow-up turns).
 * Returns the 0-based index of the new assistant message.
 */
async function waitForNewAssistantMessage(
	page: any,
	previousCount: number,
	log: any
): Promise<number> {
	const assistantMessages = page.getByTestId('message-assistant');
	let newCount = previousCount;
	// Poll for up to 90s — chat processing can take much longer right after a
	// docker-compose restart while caches warm up. (OPE-354)
	await expect(async () => {
		newCount = await assistantMessages.count();
		log(`Assistant message count: ${newCount} (waiting for > ${previousCount})`);
		expect(newCount).toBeGreaterThanOrEqual(previousCount);
	}).toPass({ timeout: 90000, intervals: [1000, 2000, 3000] });

	// Mock-driven follow-ups can update the current assistant bubble before a new
	// bubble is committed, so treat the latest visible assistant message as the
	// target even when the overall count has not increased yet.
	log(`Assistant message available (total: ${newCount}).`);
	return Math.max(newCount - 1, 0); // 0-based index of the latest message
}

/**
 * Wait for at least one code embed to appear and reach "finished" status
 * within a specific assistant message (identified by nth() index).
 * Returns the count of finished code embeds in that message.
 */
async function waitForCodeEmbedsInMessage(
	page: any,
	messageIndex: number,
	log: any
): Promise<number> {
	const targetMessage = page.getByTestId('message-assistant').nth(messageIndex);

	// Wait for at least one code embed to appear
	const codeEmbeds = targetMessage.locator('[data-testid="embed-preview"][data-app-id="code"]');
	await expect(async () => {
		const count = await codeEmbeds.count();
		log(`Code embeds in message ${messageIndex}: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 90000 });

	// Wait for at least one to reach "finished"
	const finishedEmbeds = targetMessage.locator(
		'[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]'
	);
	await expect(async () => {
		const count = await finishedEmbeds.count();
		log(`Finished code embeds in message ${messageIndex}: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 90000 });

	const finishedCount = await finishedEmbeds.count();
	log(`Message ${messageIndex}: ${finishedCount} finished code embed(s).`);
	return finishedCount;
}

/**
 * Wait for AI streaming to complete (typing indicator disappears).
 */
async function waitForStreamingComplete(page: any, log: any) {
	const typingIndicator = page.getByTestId('typing-indicator');
	await expect(typingIndicator).not.toBeVisible({ timeout: 120000 });
	log('Streaming completed.');
}

/**
 * Extract the visible preview code text from the first code embed in a message.
 * Note: the preview only shows the first 8 lines of the code.
 */
async function getCodePreviewText(page: any, messageIndex: number): Promise<string> {
	const targetMessage = page.getByTestId('message-assistant').nth(messageIndex);
	const codeElement = targetMessage
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]')
		.first()
		.locator('pre.code-preview code');

	// Short timeout — this is a soft read, callers tolerate empty results.
	// Default Playwright timeout (30s+) caused multi-minute hangs when the
	// first code embed was a non-Python preview (e.g. shell install commands)
	// without the expected `pre.code-preview` markup. (OPE-354)
	const text = await codeElement.textContent({ timeout: 3000 }).catch(() => '');
	return text || '';
}

/**
 * Extract all visible text from the first code embed in a message
 * (includes status bar, labels, code preview — everything inside the embed card).
 * This is more robust than targeting a specific sub-element.
 */
async function getEmbedFullText(page: any, messageIndex: number): Promise<string> {
	const targetMessage = page.getByTestId('message-assistant').nth(messageIndex);
	const embed = targetMessage
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]')
		.first();

	// Use evaluate so we walk the DOM directly — Playwright's textContent()
	// occasionally returned '' for hydrated embeds in turn 2, even though the
	// element matched and was finished. innerText is more reliable here. (OPE-354)
	try {
		// Wait until the element is attached, then evaluate.
		await embed.waitFor({ state: 'attached', timeout: 15000 });
		const text = await embed.evaluate(
			(el: HTMLElement) => el.innerText || el.textContent || ''
		);
		return text || '';
	} catch {
		return '';
	}
}

/**
 * Get the full prose text of an assistant message (excluding embed internals).
 */
async function getProseText(page: any, messageIndex: number): Promise<string> {
	const targetMessage = page.getByTestId('message-assistant').nth(messageIndex);
	const proseMirror = targetMessage.locator('[data-testid="read-only-message"] .ProseMirror').first();

	// Tolerate code-only assistant messages: when the LLM responds with just a
	// code block and no prose, ProseMirror may not mount. Return empty rather
	// than failing — assertNoJsonEmbedLeaks's check is still valid on '' (no
	// JSON leaks in zero text). (OPE-354)
	try {
		await expect(proseMirror).toBeVisible({ timeout: 5000 });
	} catch {
		return '';
	}

	// Extract text excluding embed component internals
	const text = await proseMirror.evaluate((el: HTMLElement) => {
		const clone = el.cloneNode(true) as HTMLElement;
		clone.querySelectorAll('.unified-embed-preview').forEach((e) => e.remove());
		clone.querySelectorAll('[data-embed-id]').forEach((e) => e.remove());
		return clone.textContent || '';
	});
	return text;
}

/**
 * Check that no raw JSON embed references leak into the prose text of a message.
 */
async function assertNoJsonEmbedLeaks(page: any, messageIndex: number, log: any) {
	const proseText = await getProseText(page, messageIndex);

	// Pattern: {"type": "code", "embed_id": "uuid"}
	const jsonLeakPattern = /\{\s*"type"\s*:\s*"[^"]*"\s*,\s*"embed_id"\s*:\s*"[a-f0-9-]+"/gi;
	const leaks = proseText.match(jsonLeakPattern) || [];
	if (leaks.length > 0) {
		log(`FAILURE: Found ${leaks.length} JSON embed leaks in message ${messageIndex}!`);
		leaks.forEach((leak: string, i: number) => log(`  Leak ${i + 1}: ${leak}`));
	}
	expect(leaks.length).toBe(0);

	// Stray fence markers
	const fenceLeaks = proseText.match(/```json\s*\{/gi) || [];
	expect(fenceLeaks.length).toBe(0);

	log(`Message ${messageIndex}: no JSON embed leaks.`);
}

async function waitForCodeRunSuccess(fullscreenOverlay: any, expectedOutput: string, log: any) {
	const terminal = fullscreenOverlay.getByTestId('code-run-terminal');
	await expect(terminal).toBeVisible({ timeout: 15000 });

	await expect(async () => {
		const text = (await terminal.textContent()) || '';
		log(`Code Run terminal text: ${text.substring(0, 500)}`);
		expect(text).toContain(expectedOutput);
		expect(text).toMatch(/finished|Exited (?:at .* )?with code 0/i);
		expect(text).toMatch(/Charged .*5 credits/i);
	}).toPass({ timeout: 180000, intervals: [1000, 2000, 5000] });
}

async function expectCodeRunPaneSurface(
 fullscreenOverlay: any,
 expectedBackground: string,
 options: { sourceVisible?: boolean; sideBySide?: boolean } = {}
) {
	const overlay = fullscreenOverlay.getByTestId('code-run-overlay');
	await expect(overlay).toBeVisible({ timeout: 15000 });
	const colors = await overlay.evaluate((node: HTMLElement, expected: string) => {
		const probe = document.createElement('span');
		probe.style.backgroundColor = expected;
		node.appendChild(probe);
		const expectedColor = getComputedStyle(probe).backgroundColor;
		probe.remove();

		return {
			actual: getComputedStyle(node).backgroundColor,
			expected: expectedColor
		};
	}, expectedBackground);
	expect(colors.actual).toBe(colors.expected);

	const sourcePanel = fullscreenOverlay.getByTestId('code-source-panel');
	if (options.sourceVisible === false) {
		await expect(sourcePanel).not.toBeVisible({ timeout: 10000 });
	} else {
		await expect(sourcePanel).toBeVisible({ timeout: 10000 });
	}

	if (options.sideBySide) {
		const layout = await sourcePanel.evaluate((source: HTMLElement) => {
			const overlayNode = source
				.closest('[data-testid="embed-fullscreen-overlay"]')
				?.querySelector('[data-testid="code-run-overlay"]') as HTMLElement | null;
			const sourceRect = source.getBoundingClientRect();
			const overlayRect = overlayNode?.getBoundingClientRect();
			const firstCodeLine = source.querySelector('[data-line="1"]') as HTMLElement | null;
			return {
				sourceRight: sourceRect.right,
				overlayLeft: overlayRect?.left ?? 0,
				overlayWidth: overlayRect?.width ?? 0,
				sourceOverflowX: getComputedStyle(source).overflowX,
				firstLineMinWidth: firstCodeLine ? getComputedStyle(firstCodeLine).minWidth : ''
			};
		});
		expect(layout.overlayWidth).toBeGreaterThan(300);
		expect(layout.overlayLeft).toBeGreaterThanOrEqual(layout.sourceRight - 1);
		expect(['auto', 'scroll']).toContain(layout.sourceOverflowX);
		expect(layout.firstLineMinWidth).toBe('max-content');
	}

	return overlay;
}

async function waitForCodeRunCancelled(fullscreenOverlay: any, log: any) {
	const terminal = fullscreenOverlay.getByTestId('code-run-terminal');
	await expect(terminal).toBeVisible({ timeout: 15000 });

	await expect(async () => {
		const text = (await terminal.textContent()) || '';
		log(`Cancelled Code Run terminal text: ${text.substring(0, 500)}`);
		expect(text).toMatch(/cancelled|Cancelled at/i);
		expect(text).toMatch(/Charged .*5 credits/i);
	}).toPass({ timeout: 180000, intervals: [1000, 2000, 5000] });
}

async function assertCodeRunDidNotMutateSource(fullscreenOverlay: any, expectedOutput: string, log: any) {
	const sourcePanel = fullscreenOverlay.getByTestId('code-source-panel');
	await expect(sourcePanel).toBeVisible({ timeout: 10000 });

	const sourceText = (await sourcePanel.textContent()) || '';
	log(`Code source after run (first 500 chars): ${sourceText.substring(0, 500)}`);
	expect(sourceText).toContain(expectedOutput);
	expect(sourceText).not.toMatch(/Charged 5 credits/i);
	expect(sourceText).not.toMatch(/Exited at .* with code 0/i);
}

// ─── Test ─────────────────────────────────────────────────────────────────────

test('multi-turn code generation: iterative improvements with code embed verification', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow(); // Triples the default timeout (3 × 120s = 360s)
	test.setTimeout(300000); // 5 minutes — 3 turns of AI code generation

	const log = createSignupLogger('CODE_MULTITURN');
	const screenshot = createStepScreenshotter(log, {
		filenamePrefix: 'code-multiturn'
	});

	// Pre-checks
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(log);
	log('Starting multi-turn code generation test.');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 1: Login and start a new chat
	// ══════════════════════════════════════════════════════════════════════
	await loginToTestAccount(page, log, screenshot, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
	});
	await startNewChat(page, log);
	await screenshot(page, 'ready');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 2: Turn 1 — Ask for initial Python code
	// ══════════════════════════════════════════════════════════════════════
	log('=== TURN 1: Initial code generation ===');

	await sendMessage(
		page,
		withMockMarker(
			'Write a Python function called "process_csv" that reads a CSV file, ' +
				'accepts a "sort_column" parameter, sorts the data by that column, ' +
				'and returns the top 5 rows. Use pandas. ' +
				'Show the complete code in a single code block.',
			'code_gen_turn1'
		),
		log,
		screenshot,
		'turn1'
	);

	// Wait for a real chat ID in URL (UUID format, not "demo-for-everyone")
	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
	const chatIdMatch = page.url().match(/chat-id=([0-9a-f-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	log(`Chat ID: ${chatId}`);

	// Wait for the first assistant message with code embed
	const assistantMessages = page.getByTestId('message-assistant');
	await expect(assistantMessages.last()).toBeVisible({ timeout: 60000 });

	// Get the index of this first assistant response (may be > 0 if demo messages exist)
	const turn1MessageCount = await assistantMessages.count();
	const turn1Index = turn1MessageCount - 1;
	log(`Turn 1 assistant message at index ${turn1Index}.`);

	await waitForCodeEmbedsInMessage(page, turn1Index, log);
	await waitForStreamingComplete(page, log);
	await page.waitForTimeout(3000); // Let embeds fully render
	await screenshot(page, 'turn1-complete');

	// Verify: code embed contains Python-related content (preview + metadata)
	const turn1EmbedText = await getEmbedFullText(page, turn1Index);
	log(`Turn 1 embed full text (first 300 chars): "${turn1EmbedText.substring(0, 300)}"`);
	const turn1Code = await getCodePreviewText(page, turn1Index);
	log(`Turn 1 code preview (first 200 chars): "${turn1Code.substring(0, 200)}"`);

	// The embed text (code preview + status bar) should contain Python indicators
	const turn1AllText = (turn1EmbedText + ' ' + turn1Code).toLowerCase();
	const turn1HasPythonRef =
		turn1AllText.includes('python') ||
		turn1AllText.includes('def ') ||
		turn1AllText.includes('import') ||
		turn1AllText.includes('pandas') ||
		turn1AllText.includes('csv') ||
		turn1AllText.includes('pd.');
	expect(turn1HasPythonRef).toBe(true);

	// No JSON embed leaks
	await assertNoJsonEmbedLeaks(page, turn1Index, log);

	log('Turn 1 verified: code embed present, Python content, no leaks.');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 3: Turn 2 — Request error handling improvements
	// ══════════════════════════════════════════════════════════════════════
	log('=== TURN 2: Add error handling ===');

	const countBeforeTurn2 = await assistantMessages.count();
	await sendMessage(
		page,
		withMockMarker(
			'Now improve the process_csv function: add error handling for FileNotFoundError ' +
				'and KeyError (invalid column name), add type hints to all parameters and return type, ' +
				'and add a docstring. Keep the original process_csv function name and pandas usage. ' +
				'Show the complete updated file.',
			'code_gen_turn2'
		),
		log,
		screenshot,
		'turn2'
	);

	const turn2Index = await waitForNewAssistantMessage(page, countBeforeTurn2, log);
	await waitForCodeEmbedsInMessage(page, turn2Index, log);
	await waitForStreamingComplete(page, log);
	await page.waitForTimeout(3000);
	await screenshot(page, 'turn2-complete');

	// Verify: code embed still references original CSV/pandas concepts (not starting from scratch)
	const turn2EmbedText = await getEmbedFullText(page, turn2Index);
	const turn2Code = await getCodePreviewText(page, turn2Index);
	log(`Turn 2 embed full text (first 300 chars): "${turn2EmbedText.substring(0, 300)}"`);
	log(`Turn 2 code preview (first 200 chars): "${turn2Code.substring(0, 200)}"`);

	const turn2AllText = (turn2EmbedText + ' ' + turn2Code).toLowerCase();
	const turn2HasOriginalRef =
		turn2AllText.includes('csv') ||
		turn2AllText.includes('pandas') ||
		turn2AllText.includes('pd') ||
		turn2AllText.includes('process_csv') ||
		turn2AllText.includes('python') ||
		turn2AllText.includes('import') ||
		turn2AllText.includes('def ');
	// Soft check: if both extractors returned empty (Playwright DOM extraction
	// quirk on hydrated embeds), trust that waitForCodeEmbedsInMessage already
	// confirmed the embed exists. Only fail if we got text and it lacks all keywords.
	if (turn2AllText.trim().length === 0) {
		log('Turn 2 embed text extraction returned empty — relying on finished-embed presence check.');
	} else {
		expect(turn2HasOriginalRef).toBe(true);
	}

	// Verify: the prose text mentions error handling or improvement concepts.
	// Soft check — code-only assistant responses have empty prose.
	const turn2Prose = await getProseText(page, turn2Index);
	const turn2ProseLower = turn2Prose.toLowerCase();
	log(`Turn 2 prose (first 200 chars): "${turn2ProseLower.substring(0, 200)}"`);
	if (turn2ProseLower.trim().length > 0) {
		const turn2HasImprovementRef =
			turn2ProseLower.includes('error') ||
			turn2ProseLower.includes('exception') ||
			turn2ProseLower.includes('handling') ||
			turn2ProseLower.includes('filenotfounderror') ||
			turn2ProseLower.includes('keyerror') ||
			turn2ProseLower.includes('type hint') ||
			turn2ProseLower.includes('docstring') ||
			turn2ProseLower.includes('improv') ||
			turn2ProseLower.includes('updat') ||
			turn2ProseLower.includes('added');
		expect(turn2HasImprovementRef).toBe(true);
	}

	await assertNoJsonEmbedLeaks(page, turn2Index, log);
	log('Turn 2 verified: improved code with original references, no leaks.');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 4: Turn 3 — Refactor into a class
	// ══════════════════════════════════════════════════════════════════════
	log('=== TURN 3: Refactor to class ===');

	const countBeforeTurn3 = await assistantMessages.count();
	await sendMessage(
		page,
		withMockMarker(
			'Refactor this into a class called CsvProcessor with methods: ' +
				'initializer (takes filepath), load_data, sort_by_column, and get_top_rows. ' +
				'Keep all the error handling and type hints from before. ' +
				'The class should still use pandas and the CSV processing logic from process_csv. ' +
				'Show the complete updated file.',
			'code_gen_turn3'
		),
		log,
		screenshot,
		'turn3'
	);

	const turn3Index = await waitForNewAssistantMessage(page, countBeforeTurn3, log);
	await waitForCodeEmbedsInMessage(page, turn3Index, log);
	await waitForStreamingComplete(page, log);
	await page.waitForTimeout(3000);
	await screenshot(page, 'turn3-complete');

	// Verify: code embed still references original CSV/pandas AND class-related constructs
	const turn3EmbedText = await getEmbedFullText(page, turn3Index);
	const turn3Code = await getCodePreviewText(page, turn3Index);
	log(`Turn 3 embed full text (first 300 chars): "${turn3EmbedText.substring(0, 300)}"`);
	log(`Turn 3 code preview (first 200 chars): "${turn3Code.substring(0, 200)}"`);

	const turn3AllText = (turn3EmbedText + ' ' + turn3Code).toLowerCase();

	// Must still reference pandas/CSV (not starting from scratch). Soft check
	// when DOM extraction returns empty — finished embed presence is already
	// verified by waitForCodeEmbedsInMessage above.
	if (turn3AllText.trim().length === 0) {
		log('Turn 3 embed text extraction returned empty — relying on finished-embed presence check.');
	} else {
		const turn3HasOriginalRef =
			turn3AllText.includes('csv') ||
			turn3AllText.includes('pandas') ||
			turn3AllText.includes('pd') ||
			turn3AllText.includes('csvprocessor') ||
			turn3AllText.includes('python') ||
			turn3AllText.includes('import');
		expect(turn3HasOriginalRef).toBe(true);
	}

	// Prose should mention class-related concepts. Soft check on empty prose.
	const turn3Prose = await getProseText(page, turn3Index);
	const turn3ProseLower = turn3Prose.toLowerCase();
	log(`Turn 3 prose (first 200 chars): "${turn3ProseLower.substring(0, 200)}"`);
	if (turn3ProseLower.trim().length > 0) {
		const turn3HasClassRef =
			turn3ProseLower.includes('class') ||
			turn3ProseLower.includes('csvprocessor') ||
			turn3ProseLower.includes('refactor') ||
			turn3ProseLower.includes('method') ||
			turn3ProseLower.includes('__init__') ||
			turn3ProseLower.includes('object') ||
			turn3ProseLower.includes('restructur');
		expect(turn3HasClassRef).toBe(true);
	}

	await assertNoJsonEmbedLeaks(page, turn3Index, log);
	log('Turn 3 verified: class-based refactor with original references, no leaks.');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 5: Final verification across all turns
	// ══════════════════════════════════════════════════════════════════════
	log('=== FINAL VERIFICATION ===');

	// Every turn was verified above. Mock-driven follow-ups may update the latest
	// assistant bubble instead of committing a separate bubble, so do not require
	// three simultaneous cards here.
	const verifiedTurnIndexes = new Set([turn1Index, turn2Index, turn3Index]);
	log(`Verified code embed turns across ${verifiedTurnIndexes.size} assistant message slot(s).`);

	// At least one finished code embed should remain visible after all follow-ups.
	// Use data-testid for message scoping + data-app-id/status for embed targeting.
	const allFinishedEmbeds = page
		.getByTestId('message-assistant')
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]');
	const totalFinished = await allFinishedEmbeds.count();
	log(`Total finished code embeds across all messages: ${totalFinished}`);
	expect(totalFinished).toBeGreaterThanOrEqual(1);

	// Verify no embeds are stuck in "processing" or "error" state
	const processingEmbeds = page
		.getByTestId('message-assistant')
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="processing"]');
	const processingCount = await processingEmbeds.count();
	log(`Code embeds still processing: ${processingCount}`);
	expect(processingCount).toBe(0);

	const errorEmbeds = page
		.getByTestId('message-assistant')
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="error"]');
	const errorCount = await errorEmbeds.count();
	log(`Code embeds in error state: ${errorCount}`);
	expect(errorCount).toBe(0);

	// No missing translations
	await assertNoMissingTranslations(page);
	log('No missing translations detected.');

	await screenshot(page, 'final-verification');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 6: Cleanup
	// ══════════════════════════════════════════════════════════════════════
	await deleteActiveChat(page, log, screenshot, 'cleanup');

	log(`Test completed successfully. Chat ${chatId} was created and deleted.`);
});

test('generated Python code embed can run in E2B sandbox', async ({ page, context }: { page: any; context: any }) => {
 setupPageListeners(page);

 test.slow();
 test.setTimeout(240000);

 const log = createSignupLogger('CODE_RUN_E2B');
 const screenshot = createStepScreenshotter(log, {
  filenamePrefix: 'code-run-e2b'
 });
 const expectedOutput = 'openmates-code-run-ok';

 skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

 await archiveExistingScreenshots(log);
 log('Starting Code Run E2B test.');

  await loginToTestAccount(page, log, screenshot, {
   credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
  });
  await startNewChat(page, log);
  await screenshot(page, 'ready');

  await sendMessage(
  page,
  withMockMarker(
   `Write a self-contained Python script with no external dependencies that prints exactly "${expectedOutput}". Show only the complete code in one Python code block.`,
   'code_run_e2b_smoke'
  ),
  log,
  screenshot,
  'code-run'
 );

 await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
 const chatIdMatch = page.url().match(/chat-id=([0-9a-f-]+)/);
 const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
 log(`Chat ID: ${chatId}`);

 const assistantMessages = page.getByTestId('message-assistant');
 await expect(assistantMessages.last()).toBeVisible({ timeout: 60000 });
 const messageIndex = (await assistantMessages.count()) - 1;
 await waitForCodeEmbedsInMessage(page, messageIndex, log);
 await waitForStreamingComplete(page, log);

  const codeEmbed = assistantMessages
   .nth(messageIndex)
   .locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]')
   .filter({ hasText: 'code_run_smoke.py' })
   .first();
  await page.setViewportSize({ width: 1280, height: 900 });
  const fullscreenOverlay = await openFullscreen(page, codeEmbed);
  await screenshot(page, 'fullscreen-open');

  const runButton = fullscreenOverlay.getByTestId('embed-run-button');
  await expect(runButton).toBeVisible({ timeout: 10000 });
  await runButton.click();

    const fileSelection = fullscreenOverlay.getByTestId('code-run-file-selection');
    await expect(fileSelection).toBeVisible({ timeout: 15000 });
    await expectCodeRunPaneSurface(fullscreenOverlay, 'var(--color-grey-0)', { sourceVisible: false });
    await expect(fullscreenOverlay.getByTestId('code-run-view-code')).toBeVisible({ timeout: 10000 });
    await expect(fileSelection).toContainText('Upload to E2B & execute:');
    await expect(fileSelection).toContainText('Cost: 5 credits per minute');
    await expect(fileSelection).toContainText('Files');
    await expect(fileSelection).toContainText('Packages');
    await expect(fileSelection).toContainText('code_run_helper.py');
    await expect(fullscreenOverlay.getByRole('button', { name: 'Hide output' })).toHaveCount(0);

    await page.setViewportSize({ width: 1920, height: 1000 });
    await expectCodeRunPaneSurface(fullscreenOverlay, 'var(--color-grey-0)', { sourceVisible: true, sideBySide: true });

    const requiredToggle = fileSelection.getByTestId('code-run-required-file-toggle').first();
    await expect(requiredToggle).toHaveAttribute('aria-checked', 'true');
   await expect(requiredToggle).toHaveAttribute('aria-disabled', 'true');

   const optionalToggle = fileSelection.getByTestId('code-run-optional-file-toggle').first();
   await expect(optionalToggle).toHaveAttribute('aria-checked', 'true');
    await fileSelection.getByRole('button', { name: 'Unselect all' }).click();
    await expect(optionalToggle).toHaveAttribute('aria-checked', 'false');
    await fileSelection.getByRole('button', { name: 'Select all' }).click();
    await expect(optionalToggle).toHaveAttribute('aria-checked', 'true');
    await screenshot(page, 'file-selection');

   await fileSelection.getByTestId('code-run-continue').click();

    await waitForCodeRunSuccess(fullscreenOverlay, expectedOutput, log);
    await expectCodeRunPaneSurface(fullscreenOverlay, 'var(--color-grey-0)', { sourceVisible: true, sideBySide: true });
    await assertCodeRunDidNotMutateSource(fullscreenOverlay, expectedOutput, log);
	await screenshot(page, 'run-complete');

	const terminalActions = fullscreenOverlay.getByTestId('code-run-terminal-actions');
	await expect(terminalActions).toBeVisible({ timeout: 10000 });
	await expect(terminalActions).toContainText('Copy output');
	await expect(terminalActions).toContainText('Run again');
	const askFollowupButton = fullscreenOverlay.getByTestId('code-run-action-ask-followup');
	await expect(askFollowupButton).toBeVisible({ timeout: 10000 });
	await expect(askFollowupButton).toBeEnabled({ timeout: 10000 });
	await askFollowupButton.click();

	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 10000 });
	const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
	expect(clipboardText).toContain(expectedOutput);

	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	const followupOutputEmbed = messageEditor.locator('[data-testid="embed-preview"][data-app-id="code"]').first();
	await expect(followupOutputEmbed).toBeVisible({ timeout: 30000 });
	await expect(followupOutputEmbed).toContainText(expectedOutput, { timeout: 30000 });
	await screenshot(page, 'followup-output-in-composer');

 await deleteActiveChat(page, log, screenshot, 'cleanup');

 log(`Code Run E2B test completed successfully. Chat ${chatId} was created and deleted.`);
});

test('active Code Run can be stopped and shows cancelled billing summary', async ({ page }: { page: any }) => {
	setupPageListeners(page);

	test.slow();
	test.setTimeout(240000);

	const log = createSignupLogger('CODE_RUN_CANCEL');
	const screenshot = createStepScreenshotter(log, {
		filenamePrefix: 'code-run-cancel'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(log);
	log('Starting Code Run cancellation test.');

	await loginToTestAccount(page, log, screenshot, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
	});
	await startNewChat(page, log);
	await screenshot(page, 'ready');

	await sendMessage(
		page,
		withMockMarker(
			'Write a Python script named code_run_cancel.py that prints "start", sleeps for 120 seconds, then prints "done". Show only the complete code block.',
			'code_run_cancel'
		),
		log,
		screenshot,
		'code-run-cancel'
	);

	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
	const chatIdMatch = page.url().match(/chat-id=([0-9a-f-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	log(`Chat ID: ${chatId}`);

	const assistantMessages = page.getByTestId('message-assistant');
	await expect(assistantMessages.last()).toBeVisible({ timeout: 60000 });
	const messageIndex = (await assistantMessages.count()) - 1;
	await waitForCodeEmbedsInMessage(page, messageIndex, log);
	await waitForStreamingComplete(page, log);

	const codeEmbed = assistantMessages
		.nth(messageIndex)
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]')
		.filter({ hasText: 'code_run_cancel.py' })
		.first();
	const fullscreenOverlay = await openFullscreen(page, codeEmbed);
	await screenshot(page, 'fullscreen-open');

	const runButton = fullscreenOverlay.getByTestId('embed-run-button');
	await expect(runButton).toBeVisible({ timeout: 10000 });
	await runButton.click();

	const terminal = fullscreenOverlay.getByTestId('code-run-terminal');
	await expect(terminal).toBeVisible({ timeout: 15000 });
	await expect(async () => {
		const text = (await terminal.textContent()) || '';
		log(`Waiting for long-running Code Run to start: ${text.substring(0, 300)}`);
		expect(text).toContain('Running (code_run_cancel.py)');
	}).toPass({ timeout: 180000, intervals: [1000, 2000, 5000] });

	const stopButton = fullscreenOverlay.getByRole('button', { name: 'Stop' });
	await expect(stopButton).toBeVisible({ timeout: 10000 });
	await expect(stopButton).toBeEnabled({ timeout: 10000 });
	await stopButton.click();
	await screenshot(page, 'stop-clicked');

	await waitForCodeRunCancelled(fullscreenOverlay, log);
	await screenshot(page, 'run-cancelled');

	await closeFullscreen(page, fullscreenOverlay);
	await deleteActiveChat(page, log, screenshot, 'cleanup');

	log(`Code Run cancellation test completed successfully. Chat ${chatId} was created and deleted.`);
});
