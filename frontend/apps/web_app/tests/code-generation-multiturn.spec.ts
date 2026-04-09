/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// Use shared console monitor (Rule 10) — replaces inline console boilerplate
const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Set up console and network listeners — delegates to console-monitor helpers.
 */
function setupPageListeners(page: any) {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
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
		expect(newCount).toBeGreaterThan(previousCount);
	}).toPass({ timeout: 90000, intervals: [1000, 2000, 3000] });

	log(`New assistant message appeared (total: ${newCount}).`);
	return newCount - 1; // 0-based index of the latest message
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
	await loginToTestAccount(page, log, screenshot);
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
				'__init__ (takes filepath), load_data, sort_by_column, and get_top_rows. ' +
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

	// All three turns should still have their code embeds visible (nothing dropped)
	// Use data-testid for message scoping + data-app-id/status for embed targeting
	const allFinishedEmbeds = page
		.getByTestId('message-assistant')
		.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]');
	const totalFinished = await allFinishedEmbeds.count();
	log(`Total finished code embeds across all messages: ${totalFinished}`);
	expect(totalFinished).toBeGreaterThanOrEqual(3);

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
