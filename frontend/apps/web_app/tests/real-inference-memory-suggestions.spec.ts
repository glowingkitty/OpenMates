/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Memory suggestions with a real model in an isolated per-run CI stack.
 *
 * Runs only in the `real_inference` CI group (protected `real-inference` environment,
 * dev-only provider keys, replay marker absent). Five example chats prove the owner's
 * rules (22 Nov): a memory is suggested only for something that will still help later
 * (lasting interest, short-lived plan, stated preference), never for a single question.
 *   1. "What is 17 plus 25?"                         -> no memory suggestion
 *   2. a one-off factual question                    -> no memory suggestion
 *   3. "I'm learning maths for an exam"              -> a memory about maths
 *   4. an upcoming trip to Lisbon                    -> a short-lived memory about the trip
 *   5. a stated preference for short answers         -> a memory about that preference
 * The Recommendations card always carries 1-3 workflow ideas, so its appearance marks the
 * end of post-processing; the test then reads every item's kind and title.
 * Spec: app-memories.suggestions.post-processor
 */
export {};

const { test, expect } = require('./console-monitor');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const {
	deleteActiveChat,
	focusMessageEditor,
	loginToTestAccount,
	startNewChat
} = require('./helpers/chat-test-helpers');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

interface Case {
	name: string;
	message: string;
	/** null: no memory suggestion allowed. Otherwise a memory about this must be suggested. */
	memory: RegExp | null;
}

const CASES: Case[] = [
	{ name: 'arithmetic', message: 'What is 17 plus 25?', memory: null },
	{ name: 'one-off fact', message: 'How tall is Mount Everest?', memory: null },
	{
		name: 'learning maths',
		message: "I'm learning maths for an exam next month. Can you explain what a derivative is?",
		memory: /math/i
	},
	{
		name: 'upcoming trip',
		message: "I'm going to Lisbon next week for four days. What should I see in the old town?",
		memory: /lisbon/i
	},
	{
		name: 'stated preference',
		message: 'Please always keep your answers short, I prefer brief answers. What is photosynthesis?',
		memory: /short|brief|concise/i
	}
];

// A memory phrased as a log of the question is the defect this spec guards against.
const QUESTION_LOG = /^(the )?(user )?(asked|wants to know|requested|inquired)\b|basic mathematical|calculation/i;

async function sendAndCollectRecommendations(page: any, message: string): Promise<{ kind: string; title: string }[]> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({
		timeout: 10_000
	});
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
	await page.keyboard.insertText(` ${message}`);
	await page.keyboard.press('Escape');
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });

	const assistant = page.getByTestId('message-assistant').last();
	await expect(assistant).toHaveAttribute('data-streaming', 'false', { timeout: 180_000 });

	const card = page.getByTestId('recommendations-card');
	await expect(card).toBeVisible({ timeout: 120_000 });
	const count = Number(await card.getAttribute('data-count'));
	const items: { kind: string; title: string }[] = [];
	for (let index = 0; index < count; index++) {
		await card.getByTestId('recommendation-dot').nth(index).click();
		const item = card.getByTestId('recommendation-item');
		await expect(card).toHaveAttribute('data-index', String(index));
		items.push({
			kind: (await item.getAttribute('data-kind')) || '',
			title: `${await item.getByTestId('recommendation-title').textContent()} ${await item
				.getByTestId('recommendation-summary')
				.textContent()}`.trim()
		});
	}
	return items;
}

for (const example of CASES) {
	// contract-test: direct surface=gui.web assertions=app-memories.suggestions.quality
	test(`memory suggestion: ${example.name}`, async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(240_000);
		requireRealInference('Memory suggestions', BASE_URL);
		if (!getTestAccount().email) {
			throw new Error('Real-inference CI requires a provisioned test account.');
		}
		const log = createSignupLogger(`REAL_MEMORY_SUGGESTIONS_${example.name.toUpperCase().replace(/\W+/g, '_')}`);
		const screenshot = createStepScreenshotter(log);
		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);

		const items = await sendAndCollectRecommendations(page, example.message);
		log(`Recommendations: ${JSON.stringify(items)}`);
		await testInfo.attach(`recommendations-${example.name}`, { body: await page.screenshot(), contentType: 'image/png' });

		const memories = items.filter((item) => item.kind === 'memory');
		if (example.memory === null) {
			expect(memories, 'no memory may be suggested for a single question').toEqual([]);
		} else {
			expect(memories.length, 'a memory about the person is expected').toBeGreaterThan(0);
			expect(memories.some((item) => example.memory!.test(item.title))).toBe(true);
		}
		for (const memory of memories) {
			expect(memory.title, 'a memory is a fact about the person, not a log of the question').not.toMatch(QUESTION_LOG);
		}
		await deleteActiveChat(page, log, screenshot, `real-memory-suggestions-${example.name}`);
	});
}
