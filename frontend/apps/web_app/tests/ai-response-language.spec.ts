/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * AI response language enforcement E2E test (OPE-8).
 *
 * Validates that the AI responds in the same language as the user's message:
 * 1. Login and start a new chat
 * 2. Send a message in German → verify AI responds in German
 * 3. Send a follow-up in English → verify AI switches to English
 *
 * This is a regression test for OPE-8: "User language is not followed".
 * The fix (commit 17377636e7) adds explicit language enforcement to the
 * system prompt based on the preprocessor's detected output_language.
 *
 * Bug history this test suite guards against:
 * - 17377636e7: AI ignored user's language when it differed from mate persona default
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

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
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

// Use slot 1 — AI inference test needs a reliable account with credits.
const {
	email: TEST_EMAIL,
	password: TEST_PASSWORD,
	otpKey: TEST_OTP_KEY
} = getTestAccount(1);

// ─── Language detection helpers ──────────────────────────────────────────────

/**
 * Common German words and patterns that indicate a German-language response.
 * Includes articles, conjunctions, prepositions, and common verbs/nouns.
 */
const GERMAN_INDICATORS = [
	'ist',
	'die',
	'der',
	'das',
	'und',
	'ein',
	'eine',
	'für',
	'mit',
	'nicht',
	'sich',
	'auf',
	'auch',
	'kann',
	'werden',
	'haben',
	'sind',
	'wird',
	'diese',
	'kann',
	'hier',
	'gibt',
	'können',
	'möchten',
	'natürlich',
	'gerne',
	'fragen',
	'antwort',
	'beispiel',
	'hilfe'
];

/**
 * Common English words that, when frequent, indicate an English-language response.
 * Weighted towards words that are rarely used in German text.
 */
const ENGLISH_INDICATORS = [
	'the',
	'is',
	'are',
	'you',
	'your',
	'this',
	'that',
	'with',
	'for',
	'have',
	'can',
	'will',
	'would',
	'could',
	'here',
	'there',
	'about',
	'from',
	'they',
	'which',
	'their',
	'been',
	'some',
	'these',
	'should',
	'because'
];

/**
 * Count how many indicator words appear in the given text.
 * Uses word boundary matching to avoid false positives from substrings.
 */
function countIndicators(text: string, indicators: string[]): number {
	const lower = text.toLowerCase();
	let count = 0;
	for (const word of indicators) {
		// Word boundary regex — matches whole words only
		const pattern = new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi');
		const matches = lower.match(pattern);
		if (matches) count += matches.length;
	}
	return count;
}

/**
 * Determine the dominant language of a text based on indicator word frequency.
 * Returns 'de' for German, 'en' for English, or 'unknown' if inconclusive.
 */
function detectLanguage(text: string): 'de' | 'en' | 'unknown' {
	const germanCount = countIndicators(text, GERMAN_INDICATORS);
	const englishCount = countIndicators(text, ENGLISH_INDICATORS);

	// Require at least 3 indicator hits to make a determination
	if (germanCount < 3 && englishCount < 3) return 'unknown';

	// The language with more indicator hits wins, with a 1.5x threshold
	// to avoid borderline cases (e.g. code-heavy responses with mixed words)
	if (germanCount > englishCount * 1.5) return 'de';
	if (englishCount > germanCount * 1.5) return 'en';

	return 'unknown';
}

/**
 * Get the full prose text of an assistant message (excluding embed internals).
 */
async function getAssistantProseText(page: any, messageIndex: number): Promise<string> {
	const targetMessage = page.getByTestId('message-assistant').nth(messageIndex);
	const proseMirror = targetMessage.getByTestId('mate-message-content').first();

	await expect(proseMirror).toBeVisible({ timeout: 10000 });

	const text = await proseMirror.evaluate((el: HTMLElement) => {
		const clone = el.cloneNode(true) as HTMLElement;
		// Remove embed previews and code blocks — they contain English keywords
		clone.querySelectorAll('.unified-embed-preview').forEach((e) => e.remove());
		clone.querySelectorAll('[data-embed-id]').forEach((e) => e.remove());
		clone.querySelectorAll('pre').forEach((e) => e.remove());
		clone.querySelectorAll('code').forEach((e) => e.remove());
		return clone.textContent || '';
	});
	return text;
}

/**
 * Wait for AI streaming to start (typing indicator appears) and then complete
 * (typing indicator disappears). This two-phase wait prevents the test from
 * reading a pre-existing message before the AI has even started responding.
 */
async function waitForStreamingStartAndComplete(
	page: any,
	log: any,
	previousAssistantCount: number
) {
	const typingIndicator = page.getByTestId('typing-indicator');
	const assistantMessages = page.getByTestId('message-assistant');

	// Phase 1: Wait for either the typing indicator or a rendered assistant message.
	try {
		await expect(async () => {
			const typingVisible = await typingIndicator.isVisible().catch(() => false);
			const assistantCount = await assistantMessages.count().catch(() => 0);
			expect(typingVisible || assistantCount > previousAssistantCount).toBeTruthy();
		}).toPass({ timeout: 20000 });
		log('AI response started or assistant message appeared.');
	} catch {
		// Fast mock responses can complete before the typing indicator is observed.
		log('WARNING: AI start signal not observed before response wait.');
	}

	// Phase 2: Require the assistant message to render. Do not block the whole
	// spec on a stale typing indicator; that hides the real failure by hitting
	// the GitHub Actions cancellation path before artifacts can upload.
	await expect(async () => {
		const assistantCount = await assistantMessages.count().catch(() => 0);
		log(`Assistant message count during response wait: ${assistantCount}`);
		expect(assistantCount).toBeGreaterThan(previousAssistantCount);
	}).toPass({ timeout: 60000 });

	await expect(typingIndicator).not.toBeVisible({ timeout: 5000 }).catch(() => {
		log('WARNING: Typing indicator still visible after assistant message rendered.');
	});
	log('Assistant response rendered.');
}

/**
 * Wait for a new assistant response to appear.
 * Returns the 0-based index of the new assistant message.
 */
async function waitForNewAssistantMessage(
	page: any,
	previousCount: number,
	log: any
): Promise<number> {
	const assistantMessages = page.getByTestId('message-assistant');
	let newCount = previousCount;
	await expect(async () => {
		newCount = await assistantMessages.count();
		log(`Assistant message count: ${newCount} (waiting for > ${previousCount})`);
		expect(newCount).toBeGreaterThan(previousCount);
	}).toPass({ timeout: 90000 });

	log(`Assistant message available (total: ${newCount}).`);
	return newCount - 1;
}

async function waitForAssistantTurnSettled(page: any, log: any): Promise<void> {
	const stopButton = page.getByTestId('stop-processing-button');
	await expect(stopButton)
		.not.toBeVisible({ timeout: 30000 })
		.catch(() => log('WARNING: stop-processing-button remained visible before next turn.'));

	const processingEmbeds = page.locator(
		'[data-testid="message-assistant"] [data-testid="embed-preview"][data-status="processing"]'
	);
	await expect
		.poll(async () => await processingEmbeds.count().catch(() => 0), { timeout: 45000 })
		.toBe(0);
	log('Assistant turn settled: no visible processing assistant embeds.');
}

// ─── Setup ───────────────────────────────────────────────────────────────────

function setupPageListeners(page: any) {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('AI responds in the same language as the user message (OPE-8)', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow(); // Triples the default timeout
	test.setTimeout(300000); // 5 minutes — 2 turns of AI conversation

	const log = createSignupLogger('AI_LANG');
	const screenshot = createStepScreenshotter(log, {
		filenamePrefix: 'ai-response-language'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(log);
	log('Starting AI response language enforcement test (OPE-8).');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 1: Login and start a new chat
	// ══════════════════════════════════════════════════════════════════════
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await screenshot(page, 'ready');

	// ══════════════════════════════════════════════════════════════════════
	// STEP 2: Send a message in German → expect German response
	// ══════════════════════════════════════════════════════════════════════
	log('=== TURN 1: German message ===');

	const assistantMessages = page.getByTestId('message-assistant');

	// Count existing assistant messages BEFORE sending so we can detect the new one
	const countBeforeTurn1 = await assistantMessages.count().catch(() => 0);
	log(`Assistant messages before turn 1: ${countBeforeTurn1}`);

	await sendMessage(
		page,
		withMockMarker(
			'Was sind die drei größten Städte in Deutschland und warum sind sie wichtig? ' +
				'Bitte antworte ausführlich auf Deutsch.',
			'ai_lang_turn1_german'
		),
		log,
		screenshot,
		'turn1'
	);

	// Wait for a real chat ID in URL
	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });

	// Wait for the AI to start and finish streaming
	await waitForStreamingStartAndComplete(page, log, countBeforeTurn1);

	// Wait for the NEW assistant message (count must increase from before)
	const turn1Index = await waitForNewAssistantMessage(page, countBeforeTurn1, log);
	log(`Turn 1 assistant message at index ${turn1Index}.`);

	await page.waitForTimeout(3000); // Let content fully render
	await screenshot(page, 'turn1-response');

	// Extract prose text and verify it's in German
	const turn1Text = await getAssistantProseText(page, turn1Index);
	log(`Turn 1 prose (first 300 chars): "${turn1Text.substring(0, 300)}"`);

	const turn1GermanCount = countIndicators(turn1Text, GERMAN_INDICATORS);
	const turn1EnglishCount = countIndicators(turn1Text, ENGLISH_INDICATORS);
	const turn1Lang = detectLanguage(turn1Text);

	log(
		`Turn 1 language detection: german=${turn1GermanCount} english=${turn1EnglishCount} → ${turn1Lang}`
	);

	// Primary assertion: response should be in German
	expect(
		turn1Lang,
		`Expected German response but got ${turn1Lang}. ` +
			`German indicators: ${turn1GermanCount}, English indicators: ${turn1EnglishCount}. ` +
			`Text: "${turn1Text.substring(0, 200)}..."`
	).toBe('de');

	log('Turn 1 verified: AI responded in German.');
	await waitForAssistantTurnSettled(page, log);

	// ══════════════════════════════════════════════════════════════════════
	// STEP 3: Send a follow-up in English → expect English response
	// ══════════════════════════════════════════════════════════════════════
	log('=== TURN 2: English follow-up ===');

	const countBeforeTurn2 = await assistantMessages.count();
	log(`Assistant messages before turn 2: ${countBeforeTurn2}`);

	await sendMessage(
		page,
		withMockMarker(
			'Now tell me about the three largest cities in France and why they are important. ' +
				'Please answer in detail in English.',
			'ai_lang_turn2_english'
		),
		log,
		screenshot,
		'turn2'
	);

	// Wait for AI to start and finish streaming, then find the new message
	await waitForStreamingStartAndComplete(page, log, countBeforeTurn2);
	const turn2Index = await waitForNewAssistantMessage(page, countBeforeTurn2, log);
	await page.waitForTimeout(3000);
	await screenshot(page, 'turn2-response');

	// Extract prose text and verify it's in English
	const turn2Text = await getAssistantProseText(page, turn2Index);
	log(`Turn 2 prose (first 300 chars): "${turn2Text.substring(0, 300)}"`);

	const turn2GermanCount = countIndicators(turn2Text, GERMAN_INDICATORS);
	const turn2EnglishCount = countIndicators(turn2Text, ENGLISH_INDICATORS);
	const turn2Lang = detectLanguage(turn2Text);

	log(
		`Turn 2 language detection: german=${turn2GermanCount} english=${turn2EnglishCount} → ${turn2Lang}`
	);

	// Primary assertion: response should be in English
	expect(
		turn2Lang,
		`Expected English response but got ${turn2Lang}. ` +
			`German indicators: ${turn2GermanCount}, English indicators: ${turn2EnglishCount}. ` +
			`Text: "${turn2Text.substring(0, 200)}..."`
	).toBe('en');

	log('Turn 2 verified: AI switched to English.');

	// ══════════════════════════════════════════════════════════════════════
	// CLEANUP: Delete the test chat
	// ══════════════════════════════════════════════════════════════════════
	await deleteActiveChat(page, log, screenshot);
	await screenshot(page, 'done');
	log('AI response language enforcement test complete (OPE-8).');
});
