/* eslint-disable @typescript-eslint/no-require-imports -- Repository Playwright helpers expose CommonJS exports. */
import { rmSync } from 'node:fs';
import type { Page, TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { buildRustCli, createRustHome, recordRust, runRust, rustEnv } = require('./helpers/rust-cli-terminal');
const { getTestAccount } = require('./signup-flow-helpers');

const MODEL = 'Mercury 3';
const MODEL_MENTION = '@Mercury-3';
const FIRST_PROMPT = 'Join the words coral and lantern with a hyphen. Reply only with the result.';
const FOLLOW_UP_PROMPT = 'Now swap the two words in your last reply. Reply only with the result.';
const FIRST_ANSWER = 'coral-lantern';
const FOLLOW_UP_ANSWER = 'lantern-coral';
const STREAMING = 'Response streaming';
const CHECKPOINT_TIMEOUT = 30_000;

type SavedMessage = { role: string; content: string; modelName: string | null };

test.describe.configure({ retries: 0 });

// contract-test: supporting surface=cli assertions=daily-ai-tests.real.semantic-signal
test('streams a real answer and a context-dependent follow-up in the terminal UI', async (
	{ page }: { page: Page }, testInfo: TestInfo,
) => {
	test.setTimeout(3_300_000);
	const appUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
	requireRealInference('Terminal chat processing', appUrl);
	if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(appUrl);
	const binary = buildRustCli(testInfo);
	const home = createRustHome('tui-chat-processing');
	const env = rustEnv(home, apiUrl, appUrl);
	const listChats = async (): Promise<Array<{ id: string }>> => {
		const result = await runRust(binary, env, ['chats', 'list', '--json'], 90_000);
		expect(result.code, 'read chat list in a fresh process').toBe(0);
		return JSON.parse(result.stdout).chats;
	};
	try {
		await loginToTestAccount(page);
		const pairing = recordRust(binary, ['login'], env, testInfo, 'pairing', { timeoutSeconds: 180 });
		try {
			const token = (await pairing.waitForOutput(/#pair=([A-Za-z0-9]+)/))[1];
			await page.goto(appUrl + '/#pair=' + token);
			await page.getByTestId('pair-allow-button').click({ timeout: 15_000 });
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			await pairing.waitForOutput(/Pairing PIN from the browser:/);
			pairing.typeText(pin);
			pairing.key('Return');
			expect((await pairing.waitForExit(90_000)).code).toBe(0);
		} finally {
			await pairing.dispose();
		}

		const previousChatIds = new Set((await listChats()).map(({ id }) => id));
		const steps = [
			{ name: 'chat-home', wait_for: 'Ask anything, or /help', wait_timeout_ms: CHECKPOINT_TIMEOUT },
			{ name: 'first-request', text: `${MODEL_MENTION} ${FIRST_PROMPT}` },
			{ name: 'first-stream', key: 'Return', wait_for: STREAMING, wait_timeout_ms: CHECKPOINT_TIMEOUT },
			{ name: 'first-answer', wait_for: FIRST_ANSWER, wait_for_absent: STREAMING, wait_timeout_ms: CHECKPOINT_TIMEOUT, hold_ms: 600 },
			{ name: 'follow-up', text: `${MODEL_MENTION} ${FOLLOW_UP_PROMPT}` },
			{ name: 'follow-up-stream', key: 'Return', wait_for: STREAMING, wait_timeout_ms: CHECKPOINT_TIMEOUT },
			{ name: 'follow-up-answer', wait_for: FOLLOW_UP_ANSWER, wait_for_absent: STREAMING, wait_timeout_ms: CHECKPOINT_TIMEOUT, hold_ms: 600 },
			{ name: 'exit-command', text: '/exit' },
			{ name: 'exit', key: 'Return' },
		];
		const terminal = recordRust(binary, [], env, testInfo, 'real-chat-processing', {
			timeoutSeconds: 240,
			steps,
		});
		try {
			const result = await terminal.waitForExit(245_000);
			expect(result.code, 'terminal exits after both replies').toBe(0);
			expect(result.manifest.input_checkpoints?.map((checkpoint: { name: string }) => checkpoint.name))
				.toEqual(steps.map(({ name }) => name));
		} finally {
			await terminal.dispose();
		}

		const newChats = (await listChats()).filter(({ id }) => !previousChatIds.has(id));
		expect(newChats, 'both interactive sends belong to one newly saved chat').toHaveLength(1);
		const read = await runRust(binary, env, ['chats', 'show', newChats[0].id, '--json'], 90_000);
		expect(read.code, 'read saved chat in a fresh process').toBe(0);
		const { messages }: { messages: SavedMessage[] } = JSON.parse(read.stdout);
		const turns = messages.filter(({ role }) => role === 'user' || role === 'assistant')
			.map(({ role, content, modelName }) => ({ role, content: content.trim(), modelName }));
		expect(turns).toEqual([
			expect.objectContaining({ role: 'user', content: expect.stringContaining(FIRST_PROMPT) }),
			expect.objectContaining({ role: 'assistant', content: FIRST_ANSWER, modelName: MODEL }),
			expect.objectContaining({ role: 'user', content: expect.stringContaining(FOLLOW_UP_PROMPT) }),
			expect.objectContaining({ role: 'assistant', content: FOLLOW_UP_ANSWER, modelName: MODEL }),
		]);
	} finally {
		rmSync(home, { recursive: true, force: true });
	}
});
