/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: required reason=new_provider_result (the recording shows each answer with its shopping results)
/**
 * Product search from a photo or a description: where to buy, cheapest offer, used nearby
 * (dev-only real-inference proof).
 *
 * Runs without mocks against the deployed dev stack through
 * scripts/shopping_price_compare_web_real_test.py. The cases live outside the repository
 * (SHOPPING_REAL_CASES names a JSON file; its images sit next to it), so no product photo
 * or personal shopping list is committed:
 *
 *   [{"name": "photo-en", "prompt": "Where can I buy this cheapest?", "image": "product.jpg",
 *     "expect": {"identifies": "Example Brand X100", "used": false}}]
 *
 * Each case starts a new chat, optionally attaches its image, sends the prompt and records the
 * answer text, the apps used, the shopping result cards and inline offers and a screenshot. With
 * SHOPPING_REAL_STRICT=1 a case passes only when the answer names the expected product, the
 * Shopping app ran, offers are shown as results, the answer carries clickable links (no raw markdown
 * link text, e.g. inside a table) and a euro price, and a used request shows used offers. Every turn
 * mentions @Gemini-3.8-Flash and the persisted model must be Gemini 3.8 Flash.
 * Without it the run only records (baseline). Never run in CI: it needs real providers.
 */
import type { Page } from '@playwright/test';

const fs = require('fs');
const path = require('path');
const { expect, test } = require('./helpers/cookie-audit');
const {
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type ShoppingCase = {
	name: string;
	prompt: string;
	image?: string;
	expect?: { identifies?: string; used?: boolean };
};

const ANSWER_TIMEOUT_MS = 300_000;
const STRICT = process.env.SHOPPING_REAL_STRICT === '1';
const CASES_FILE = process.env.SHOPPING_REAL_CASES || '';

function loadCases(): ShoppingCase[] {
	if (!CASES_FILE || !fs.existsSync(CASES_FILE)) return [];
	const cases = JSON.parse(fs.readFileSync(CASES_FILE, 'utf8'));
	const only = (process.env.SHOPPING_REAL_ONLY || '').split(',').filter(Boolean);
	return only.length ? cases.filter((item: ShoppingCase) => only.includes(item.name)) : cases;
}

/** The turn is over when the stop button and typing indicator stay hidden for 5 s. */
async function waitForIdle(page: Page): Promise<void> {
	const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
	let idleSince = 0;
	await expect
		.poll(
			async () => {
				if ((await busy.count()) > 0) {
					idleSince = 0;
					return false;
				}
				idleSince ||= Date.now();
				return Date.now() - idleSince >= 5_000;
			},
			{ timeout: ANSWER_TIMEOUT_MS, intervals: [1_000] }
		)
		.toBe(true);
}

async function attachImage(page: Page, file: string, log: any): Promise<void> {
	const input = page.locator('input[type="file"][multiple]');
	await expect(input).toBeAttached({ timeout: 10_000 });
	// A unique suffix keeps the upload from reusing a stale row for the same image hash.
	const buffer = Buffer.concat([fs.readFileSync(file), Buffer.from(`\nopenmates-e2e-${Date.now()}`)]);
	await input.setInputFiles({ name: path.basename(file), mimeType: 'image/jpeg', buffer });
	const editor = page.getByTestId('message-editor');
	const preview = editor.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="view"]');
	await expect(preview.first()).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
	const overlay = page.getByTestId('embed-fullscreen-overlay');
	if (await overlay.first().isVisible().catch(() => false)) await page.keyboard.press('Escape');
	log('Image attached.', { image: path.basename(file) });
}

/** Picks Gemini 3.8 Flash for this turn through the @-mention dropdown at the caret. */
async function mentionModel(page: Page): Promise<void> {
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
}

async function send(page: Page, prompt: string, file: string | null, log: any): Promise<void> {
	if (file) await attachImage(page, file, log);
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]');
	await focusMessageEditor(editor);
	if (file) {
		await editable.press('ControlOrMeta+End');
		await editable.press('ArrowRight');
		await editable.press('Enter');
	}
	await mentionModel(page);
	await page.keyboard.insertText(prompt);
	await expect(editable).toContainText(prompt);
	const users = page.getByTestId('message-user');
	const before = await users.count().catch(() => 0);
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled({ timeout: 15_000 });
	await sendButton.click();
	await expect.poll(async () => users.count(), { timeout: 60_000 }).toBeGreaterThan(before);
}

async function shoppingCards(answer: any): Promise<string[]> {
	const cards = answer.locator('[data-testid="embed-preview"][data-app-id="shopping"]');
	const count = await cards.count();
	const texts: string[] = [];
	for (let index = 0; index < count; index++) texts.push((await cards.nth(index).innerText()).trim());
	return texts;
}

test.describe('shopping price comparison (real dev inference)', () => {
	const cases = loadCases();

	// contract-test: direct surface=gui.web assertions=shopping-search.answer.identify-then-compare,shopping-search.compare.total-price,shopping-search.compare.condition
	test('product questions with and without a photo find where to buy and the cheapest offer', async ({ page }: { page: Page }, testInfo: any) => {
		test.skip(Boolean(process.env.E2E_USE_MOCKS), 'Real dev inference only.');
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		test.skip(cases.length === 0, 'SHOPPING_REAL_CASES names no cases.');
		test.setTimeout(cases.length * ANSWER_TIMEOUT_MS + 120_000);
		await page.setViewportSize({ width: 1400, height: 1000 });
		const log = createSignupLogger('SHOPPING_PRICE_COMPARE');
		const screenshot = createStepScreenshotter(log);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await setChatSidebarOpen(page, false, log);

		const records: any[] = [];
		for (const item of cases) {
			await startNewChat(page, log);
			await send(page, item.prompt, item.image ? path.join(path.dirname(CASES_FILE), item.image) : null, log);
			await waitForAssistantMessage(page, { which: 'last', timeout: ANSWER_TIMEOUT_MS, logCheckpoint: log });
			await waitForIdle(page);
			const answer = page.getByTestId('message-assistant').last();
			const text = (await answer.innerText()).trim();
			const cards = await shoppingCards(answer);
			// "Thought & used the Shopping app" in the activity summary names the apps that ran.
			const summary = answer.getByTestId('assistant-activity-summary-text').first();
			const usedApps = (await summary.count()) ? (await summary.innerText({ timeout: 10_000 })).trim() : '';
			const inlineOffers = await answer.locator('.embed-inline-link').count();
			const links = await answer.locator('a[href^="http"]').evaluateAll((nodes: any[]) =>
				nodes.map((node) => node.href)
			);
			const generatedBy = ((await answer.getByTestId('generated-by').first().textContent({ timeout: 10_000 }).catch(() => '')) || '').trim();
			const record = { name: item.name, prompt: item.prompt, image: item.image || null, usedApps, generatedBy, text, cards, inlineOffers, links };
			records.push(record);
			await testInfo.attach(`${item.name}.png`, { body: await page.screenshot({ fullPage: false }), contentType: 'image/png' });
			await testInfo.attach(`${item.name}.json`, { body: JSON.stringify(record, null, 2), contentType: 'application/json' });
			log('Answer recorded.', { name: item.name, cards: cards.length, links: links.length });

			if (STRICT) {
				const expected = item.expect || {};
				// Brands are written in varying case ("ELZO", "Elzo"); the name itself must appear.
				if (expected.identifies)
					expect
						.soft(text.toLowerCase(), `${item.name}: names the product`)
						.toContain(String(expected.identifies).toLowerCase());
				expect.soft(usedApps, `${item.name}: a shopping search ran`).toMatch(/Shopping/);
				expect.soft(cards.length + inlineOffers, `${item.name}: offers are shown as results`).toBeGreaterThan(0);
				expect.soft(text, `${item.name}: shows a euro price`).toMatch(/\d[\d.,]*\s?€|€\s?\d/);
				// Offer links render as inline embed links (role=link) or plain anchors; markdown that stayed text is not a link.
				expect.soft(links.length + inlineOffers, `${item.name}: offers carry links`).toBeGreaterThan(0);
				expect.soft(text, `${item.name}: no raw markdown links`).not.toMatch(/\]\(https?:\/\//);
				expect.soft(generatedBy, `${item.name}: answered by Gemini 3.8 Flash`).toMatch(/Gemini 3\.8 Flash/i);
				if (expected.used) expect.soft(text, `${item.name}: shows used offers`).toMatch(/used|gebraucht/i);
			}
		}
		fs.writeFileSync(testInfo.outputPath('shopping-records.json'), JSON.stringify(records, null, 2));
		await testInfo.attach('shopping-records.json', { path: testInfo.outputPath('shopping-records.json'), contentType: 'application/json' });
	});
});
