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
const RECIPE_OPENING = 'Build a working recipe app in one self-contained HTML code block named recipe.html. Start the code block straight away.';
const RECIPE_DETAILS = 'Include 30 example recipes, ingredient search, adjustable servings, and favorites. Set the header background to blue (#0055ff) initially.';
const RECIPE = RECIPE_OPENING + ' ' + RECIPE_DETAILS;
const RED = 'Make the header red (#d00000) in this same recipe app.';
const FONT = 'Use Lexend Deca in this same recipe app, and keep the red header.';
const STREAMING = 'Response streaming';
const STEP_TIMEOUT = 30_000;
const BLUE_HEADER = /(?:background|background-color)\s*:\s*#0055ff\b/i;
const RED_HEADER = /(?:background|background-color)\s*:\s*#d00000\b/i;
const LEXEND_DECA = /font-family\s*:\s*['"]?Lexend Deca\b/i;

type SavedMessage = { role: string; content: string; modelName: string | null };

function codeReferences(messages: SavedMessage[]): string[] {
	const ids = new Set<string>();
	for (const { role, content } of messages) {
		if (role !== 'assistant') continue;
		for (const match of content.matchAll(/`{3}json(?:_embed)?[ \t]*\r?\n([\s\S]*?)\r?\n\s*`{3}/g)) {
			try {
				const { type, embed_id } = JSON.parse(match[1]);
				if (type === 'code' && typeof embed_id === 'string') ids.add(embed_id);
			} catch {
				// A Markdown JSON example need not be an artifact reference.
			}
		}
	}
	return [...ids];
}

test.describe.configure({ retries: 0 });

// contract-test: supporting surface=cli assertions=chat-queued-followups.steering.safe-boundary,daily-ai-tests.real.semantic-signal
test('applies two corrections to the same recipe app from the terminal while its reply is streaming', async (
	{ page }: { page: Page }, testInfo: TestInfo,
) => {
	test.setTimeout(3_300_000);
	const appUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
	requireRealInference('Terminal artifact steering', appUrl);
	if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(appUrl);
	const binary = buildRustCli(testInfo);
	const home = createRustHome('tui-artifact-steering');
	const env = rustEnv(home, apiUrl, appUrl);
	const listChats = async (): Promise<Array<{ id: string }>> => {
		const result = await runRust(binary, env, ['chats', 'list', '--json'], 90_000);
		expect(result.code, 'read newly saved chat in a fresh process').toBe(0);
		return JSON.parse(result.stdout).chats;
	};
	try {
		await loginToTestAccount(page);
		const pairing = recordRust(binary, ['login'], env, testInfo, 'artifact-pairing', { timeoutSeconds: 180 });
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

		const priorChats = new Set((await listChats()).map(({ id }) => id));
		const steps = [
			{ name: 'chat-home', wait_for: 'Ask anything, or /help', wait_timeout_ms: STEP_TIMEOUT },
			// The recorder bounds each text input. Both pieces form one composer draft.
			{ name: 'recipe-request', text: MODEL_MENTION + ' ' + RECIPE_OPENING },
			{ name: 'recipe-details', text: ' ' + RECIPE_DETAILS },
			{ name: 'recipe-send', key: 'Return', wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'original-card', wait_for: '/embed ', wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'red-request', text: RED, wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'red-send', key: 'Return', wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'font-request', text: FONT, wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'font-send', key: 'Return' },
		];
		const terminal = recordRust(binary, [], env, testInfo, 'artifact-steering', { timeoutSeconds: 300, steps });
		try {
			const card = (await terminal.waitForOutput(/\/embed\s+([a-f0-9]{8})\b/, 90_000))[1];
			await terminal.waitForOutput(/Lexend Deca/, STEP_TIMEOUT);
			let artifactId = '';
			await expect.poll(async () => {
				const chats = (await listChats()).filter(({ id }) => !priorChats.has(id));
				if (chats.length !== 1) return 'waiting for the original chat';
				const read = await runRust(binary, env, ['chats', 'show', chats[0].id, '--json']);
				if (read.code !== 0) return 'waiting for encrypted chat history';
				const { messages }: { messages: SavedMessage[] } = JSON.parse(read.stdout);
				const userTurns = messages.filter(({ role }) => role === 'user').map(({ content }) => content.trim());
				if (userTurns.length < 3) return 'waiting for both saved corrections';
				expect(userTurns).toEqual([expect.stringContaining(RECIPE), RED, FONT]);
				const answers = messages.filter(({ role }) => role === 'assistant');
				if (!answers.length) return 'waiting for the original assistant reply';
				expect(answers.every(({ modelName }) => modelName === MODEL)).toBe(true);
				const refs = codeReferences(messages);
				if (!refs.length) return 'waiting for the saved card reference';
				expect(refs.map((id) => id.slice(0, 8))).toEqual([card]);
				artifactId = refs[0];
				const readArtifact = await runRust(binary, env, ['embeds', 'show', artifactId, '--json']);
				if (readArtifact.code !== 0) return 'waiting for the finished artifact';
				const code = JSON.parse(readArtifact.stdout).fields?.content?.code || '';
				return RED_HEADER.test(code) && LEXEND_DECA.test(code) ? 'both changes present' : 'waiting for source revisions';
			}, { timeout: 120_000, intervals: [1_000, 2_500, 5_000] }).toBe('both changes present');

			const original = await runRust(binary, env, [
				'embeds', 'versions', 'show', artifactId, '--version', '1', '--json',
			]);
			expect(original.code, 'the last working source has a saved version').toBe(0);
			const originalSource = JSON.parse(original.stdout).content;
			expect(originalSource).toMatch(BLUE_HEADER);
			expect(originalSource).not.toMatch(RED_HEADER);
			expect(originalSource).not.toMatch(LEXEND_DECA);

			terminal.typeText('/exit');
			terminal.key('Return');
			const result = await terminal.waitForExit(STEP_TIMEOUT);
			expect(result.code).toBe(0);
			expect(result.manifest.input_checkpoints?.map((checkpoint: { name: string }) => checkpoint.name))
				.toEqual(steps.map(({ name }) => name));

			const finalSource = recordRust(binary, ['embeds', 'show', artifactId], env, testInfo, 'artifact-revised-source');
			try {
				expect((await finalSource.waitForExit()).code).toBe(0);
			} finally {
				await finalSource.dispose();
			}
		} finally {
			await terminal.dispose();
		}
	} finally {
		rmSync(home, { recursive: true, force: true });
	}
});
