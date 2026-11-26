/* eslint-disable @typescript-eslint/no-require-imports -- Repository Playwright helpers expose CommonJS exports. */
import { rmSync } from 'node:fs';
import type { Page, TestInfo } from '@playwright/test';
import { recordRecipeProgress } from './helpers/real-tui-artifact-steering-progress';
import { inspectOfflineRecipeHeader } from './helpers/offline-recipe-header';

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
	const phase = recordRecipeProgress(testInfo.outputPath('real-tui-artifact-steering-progress.json'));
	const appUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
	requireRealInference('Terminal artifact steering', appUrl);
	if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');
	phase('prerequisites_passed');

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(appUrl);
	phase('build_started');
	const binary = buildRustCli(testInfo);
	phase('build_ready');
	const home = createRustHome('tui-artifact-steering');
	const env = rustEnv(home, apiUrl, appUrl);
	const listChats = async (): Promise<Array<{ id: string }>> => {
		const result = await runRust(binary, env, ['chats', 'list', '--json'], 90_000);
		expect(result.code, 'read newly saved chat in a fresh process').toBe(0);
		return JSON.parse(result.stdout).chats;
	};
	try {
		await loginToTestAccount(page);
		phase('pairing_started');
		const pairing = recordRust(binary, ['login'], env, testInfo, 'artifact-pairing', { timeoutSeconds: 180 });
		try {
			const token = (await pairing.waitForOutput(/#pair=([A-Za-z0-9]+)/))[1];
			phase('pairing_offer_ready');
			await page.goto(appUrl + '/#pair=' + token);
			await page.getByTestId('pair-allow-button').click({ timeout: 15_000 });
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			phase('browser_pin_ready');
			await pairing.waitForOutput(/Pairing PIN from the browser:/);
			pairing.typeText(pin);
			pairing.key('Return');
			phase('pairing_pin_submitted');
			expect((await pairing.waitForExit(90_000)).code).toBe(0);
			phase('pairing_completed');
		} finally {
			await pairing.dispose();
		}

		const priorChats = new Set((await listChats()).map(({ id }) => id));
		phase('initial_history_read');
		const steps = [
			{ name: 'chat-home', wait_for: 'Ask anything, or /help', wait_timeout_ms: STEP_TIMEOUT },
			// The recorder bounds each text input. Both pieces form one composer draft.
			{ name: 'recipe-request', text: MODEL_MENTION + ' ' + RECIPE_OPENING },
			{ name: 'recipe-details', text: ' ' + RECIPE_DETAILS },
			{ name: 'recipe-send', key: 'Return', wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'original-card', wait_for: '/embed ', capture_code_card: true, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'red-request', text: RED, wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'red-send', key: 'Return', wait_for: STREAMING, wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'font-request', text: FONT, wait_for: STREAMING, wait_for_also: 'Lexend Deca', wait_timeout_ms: STEP_TIMEOUT },
			{ name: 'font-send', key: 'Return' },
		];
		const originalCardStep = steps.findIndex(({ name }) => name === 'original-card');
		const fontStep = steps.findIndex(({ name }) => name === 'font-send');
		const terminal = recordRust(binary, [], env, testInfo, 'artifact-steering', {
			timeoutSeconds: 300,
			steps,
			onInputProgress({ index, completed }: { index: number; completed: boolean }) {
				switch (steps[index].name) {
				case 'chat-home': if (completed) phase('composer_ready'); break;
				case 'recipe-send': phase(completed ? 'original_streaming' : 'original_sent'); break;
				case 'original-card': if (completed) phase('original_card_visible'); break;
				case 'red-send': phase(completed ? 'red_step_completed' : 'red_sent'); break;
				case 'font-request': if (completed) phase('font_preview_visible'); break;
				case 'font-send': if (completed) phase('font_sent'); break;
				}
			},
		});
		phase('terminal_started');
		try {
			const { card } = await terminal.waitForInputCheckpoint(originalCardStep, 90_000);
			// The original direct Code reference gets the first native alias in this new chat.
			expect(card).toBe('emb-v-1');
			await terminal.waitForInputCheckpoint(fontStep, STEP_TIMEOUT);
			const browser = page.context().browser();
			if (!browser) throw new Error('The offline recipe style check requires Chromium');
			let artifactId = '';
			await expect.poll(async () => {
				const chats = (await listChats()).filter(({ id }) => !priorChats.has(id));
				if (chats.length !== 1) return 'waiting for the original chat';
				phase('one_chat');
				const read = await runRust(binary, env, ['chats', 'show', chats[0].id, '--json']);
				if (read.code !== 0) return 'waiting for encrypted chat history';
				const { messages }: { messages: SavedMessage[] } = JSON.parse(read.stdout);
				const userTurns = messages.filter(({ role }) => role === 'user').map(({ content }) => content.trim());
				if (userTurns.length < 3) return 'waiting for both saved corrections';
				expect(userTurns).toEqual([expect.stringContaining(RECIPE), RED, FONT]);
				phase('all_three_user_turns');
				const answers = messages.filter(({ role }) => role === 'assistant');
				if (!answers.length) return 'waiting for the original assistant reply';
				expect(answers.every(({ modelName }) => modelName === MODEL)).toBe(true);
				phase('mercury_replies');
				const originalRefs = codeReferences([answers[0]]);
				if (!originalRefs.length) return 'waiting for the original saved Code reference';
				expect(originalRefs).toEqual([
					expect.stringMatching(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/),
				]);
				expect(codeReferences(messages)).toEqual(originalRefs);
				phase('one_matching_card');
				[artifactId] = originalRefs;
				const readArtifact = await runRust(binary, env, ['embeds', 'show', artifactId, '--json']);
				if (readArtifact.code !== 0) return 'waiting for the finished artifact';
				const artifact = JSON.parse(readArtifact.stdout);
				expect(artifact.id).toBe(artifactId);
				const code = artifact.fields?.content?.code || '';
				phase('latest_source_read');
				const { red, lexend } = await inspectOfflineRecipeHeader(browser, code);
				if (red) phase('latest_header_red');
				if (lexend) phase('latest_font_lexend');
				return red && lexend ? 'both changes present' : 'waiting for source revisions';
			}, { timeout: 120_000, intervals: [1_000, 2_500, 5_000] }).toBe('both changes present');
			phase('latest_source_verified');

			const original = await runRust(binary, env, [
				'embeds', 'versions', 'show', artifactId, '--version', '1', '--json',
			]);
			expect(original.code, 'the last working source has a saved version').toBe(0);
			const originalVersion = JSON.parse(original.stdout);
			expect(originalVersion.embed_id).toBe(artifactId);
			expect(originalVersion.version_number).toBe(1);
			const originalSource = originalVersion.content;
			phase('previous_source_read');
			const previousStyle = await inspectOfflineRecipeHeader(browser, originalSource);
			expect(previousStyle.blue, 'version one header is blue').toBe(true);
			expect(previousStyle.red, 'version one header has no red correction').toBe(false);
			expect(previousStyle.hasLexend, 'version one header has no Lexend Deca correction').toBe(false);
			phase('previous_source_verified');

			// Resolve the durable UUID in this same terminal. The detail label comes
			// from the chat's existing alias registry, so a replaced card cannot pass.
			terminal.typeText(`/embed ${artifactId}`);
			terminal.key('Return');
			await terminal.waitForOutput(/Code · Code {2}· {2}emb-v-1\b/, STEP_TIMEOUT).catch(() => {
				throw new Error('The durable Code artifact did not open with the original terminal alias');
			});

			terminal.typeText('/exit');
			terminal.key('Return');
			const result = await terminal.waitForExit(STEP_TIMEOUT);
			expect(result.code).toBe(0);
			phase('terminal_exit_verified');
			expect(result.manifest.input_checkpoints?.map((checkpoint: { name: string }) => checkpoint.name))
				.toEqual(steps.map(({ name }) => name));
			phase('input_plan_verified');

			const finalSource = recordRust(binary, ['embeds', 'show', artifactId], env, testInfo, 'artifact-revised-source');
			try {
				expect((await finalSource.waitForExit()).code).toBe(0);
				phase('revised_source_visible');
			} finally {
				await finalSource.dispose();
			}
		} finally {
			await terminal.dispose();
		}
	} finally {
		rmSync(home, { recursive: true, force: true });
	}
	phase('passed');
});
