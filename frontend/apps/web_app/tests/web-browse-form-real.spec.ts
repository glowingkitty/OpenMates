/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: required reason=new_flow (the recording shows each question, each filled field and the summary before submit)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Fill a web form together with the user (dev-only real-inference proof).
 *
 * Runs without mocks against the deployed dev stack through
 * scripts/web_browse_form_web_real_test.py. The form address and the synthetic
 * persona live outside the repository (BROWSE_FORM_CASE names a JSON file):
 *
 *   {"prompt": "Can we fill out this form together? ... https://forms.example.org/apply?event=x",
 *    "answers": [{"match": "e-?mail", "answer": "alex.rivera.demo@example.org"}, ...],
 *    "fallback": "I'm not sure. What would you suggest? Please use your suggestion.",
 *    "maxTurns": 14}
 *
 * The test sends the prompt in a new chat and then plays the user: each reply is
 * answered with the first persona answer whose pattern matches the assistant's
 * last question, else the fallback. It stops when the assistant shows the
 * summary before submitting and then says not to submit. Every turn mentions
 * @Gemini-3.8-Flash. With BROWSE_FORM_STRICT=1 the run asserts that Browse
 * started on its own, every reply asks at most one form question, every turn
 * after the first continues Browse, the form never shows a not-found page, a
 * summary arrives before the final submit and nothing is submitted. Never run
 * in CI: it needs real providers and a live third-party form.
 */
import type { Page } from '@playwright/test';

const fs = require('fs');
const { expect, test } = require('./helpers/cookie-audit');
const {
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type FormCase = {
	prompt: string;
	answers: Array<{ match: string; answer: string }>;
	fallback: string;
	maxTurns?: number;
};

const TURN_TIMEOUT_MS = 300_000;
const STRICT = process.env.BROWSE_FORM_STRICT === '1';
const CASE_FILE = process.env.BROWSE_FORM_CASE || '';
const SUMMARY = /summary|here(?:'s| is) everything|all (?:your )?answers|review (?:your|the) answers/i;
const SUBMIT_QUESTION = /submit|send (?:it|the form)|confirm/i;
const NOT_FOUND = /event not found|page not found|404/i;
const STOP_MESSAGE = "Thanks, that's all for now. Please don't submit the form.";

function loadCase(): FormCase | null {
	return CASE_FILE && fs.existsSync(CASE_FILE) ? JSON.parse(fs.readFileSync(CASE_FILE, 'utf8')) : null;
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
			{ timeout: TURN_TIMEOUT_MS, intervals: [1_000] }
		)
		.toBe(true);
}

async function mentionModel(page: Page): Promise<void> {
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
}

async function send(page: Page, text: string): Promise<void> {
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]');
	await focusMessageEditor(editor);
	await mentionModel(page);
	await page.keyboard.insertText(text);
	await expect(editable).toContainText(text.slice(0, 40));
	const users = page.getByTestId('message-user');
	const before = await users.count().catch(() => 0);
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled({ timeout: 15_000 });
	await sendButton.click();
	await expect.poll(async () => users.count(), { timeout: 60_000 }).toBeGreaterThan(before);
}

/** The last question the reply asks; the persona answers that one. */
function lastQuestion(text: string): string {
	const questions = text.split(/\n+/).filter((line) => line.trim().endsWith('?'));
	return questions.length ? questions[questions.length - 1] : text.slice(-400);
}

function personaAnswer(item: FormCase, question: string, used: Set<number>): string {
	const index = item.answers.findIndex((entry, i) => !used.has(i) && new RegExp(entry.match, 'i').test(question));
	if (index < 0) return item.fallback;
	used.add(index);
	return item.answers[index].answer;
}

async function browseEmbeds(answer: any): Promise<number> {
	return answer.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="browse"]').count();
}

test.describe('web browse form with the user (real dev inference)', () => {
	const item = loadCase();

	// contract-test: direct surface=gui.web assertions=web-browse.form-with-user,web-browse.dispatch-and-routing,web-browse.session-and-run
	test('fills a JavaScript form one question per turn in one browser session and never submits', async ({ page }: { page: Page }, testInfo: any) => {
		test.skip(Boolean(process.env.E2E_USE_MOCKS), 'Real dev inference only.');
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		test.skip(!item, 'BROWSE_FORM_CASE names no case.');
		const maxTurns = item!.maxTurns || 14;
		test.setTimeout((maxTurns + 2) * TURN_TIMEOUT_MS);
		await page.setViewportSize({ width: 1400, height: 1000 });
		const log = createSignupLogger('BROWSE_FORM');
		const screenshot = createStepScreenshotter(log);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await setChatSidebarOpen(page, false, log);
		await startNewChat(page, log);

		const turns: any[] = [];
		const used = new Set<number>();
		let message = item!.prompt;
		let summarized = false;
		for (let turn = 0; turn <= maxTurns; turn++) {
			await send(page, message);
			await waitForAssistantMessage(page, { which: 'last', timeout: TURN_TIMEOUT_MS, logCheckpoint: log });
			await waitForIdle(page);
			const answer = page.getByTestId('message-assistant').last();
			await answer.scrollIntoViewIfNeeded();
			const text = (await answer.innerText()).trim();
			const record = {
				turn,
				user: message,
				assistant: text,
				browseEmbeds: await browseEmbeds(answer),
				questions: (text.match(/\?/g) || []).length,
				generatedBy: ((await answer.getByTestId('generated-by').first().textContent({ timeout: 10_000 }).catch(() => '')) || '').trim()
			};
			turns.push(record);
			await testInfo.attach(`turn-${String(turn).padStart(2, '0')}.png`, { body: await page.screenshot({ fullPage: false }), contentType: 'image/png' });
			log('Turn recorded.', { turn, browseEmbeds: record.browseEmbeds, questions: record.questions });
			if (message === STOP_MESSAGE) break;
			if (SUMMARY.test(text) && SUBMIT_QUESTION.test(text)) {
				summarized = true;
				message = STOP_MESSAGE;
				continue;
			}
			if (turn === maxTurns - 1) {
				message = STOP_MESSAGE;
				continue;
			}
			message = personaAnswer(item!, lastQuestion(text), used);
		}
		fs.writeFileSync(testInfo.outputPath('form-turns.json'), JSON.stringify(turns, null, 2));
		await testInfo.attach('form-turns.json', { path: testInfo.outputPath('form-turns.json'), contentType: 'application/json' });

		if (STRICT) {
			expect.soft(turns[0].browseEmbeds, 'Browse starts on its own for the form link').toBeGreaterThan(0);
			for (const record of turns.slice(1, -1)) {
				expect.soft(record.browseEmbeds, `turn ${record.turn}: the answer is filled through Browse`).toBeGreaterThan(0);
			}
			for (const record of turns.slice(0, -1)) {
				expect.soft(record.questions, `turn ${record.turn}: at most one question per reply`).toBeLessThanOrEqual(2);
				expect.soft(record.assistant, `turn ${record.turn}: the form is never lost`).not.toMatch(NOT_FOUND);
				expect.soft(record.generatedBy, `turn ${record.turn}: answered by Gemini 3.8 Flash`).toMatch(/Gemini 3\.8 Flash/i);
			}
			expect.soft(summarized, 'a summary of every answer comes before the final submit').toBe(true);
			expect.soft(turns[turns.length - 1].assistant, 'the form was not submitted').not.toMatch(/(?:has been|was|I) submitted/i);
		}
	});
});
