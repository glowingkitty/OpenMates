/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI contract for default AI model routing.
 *
 * Proves the settings API and chat WebSocket path honor default model choices
 * without browser composer, IndexedDB, TipTap, or Svelte state. The web E2E can
 * then focus on settings UI and send-path behavior when this contract is green.
 *
 * Architecture context: docs/architecture/ai_model_selection.md
 */
export {};

const { test, expect } = require('./console-monitor');
const { withMockMarker } = require('./signup-flow-helpers');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');

const MISTRAL_MODEL_ID = 'mistral/mistral-small-latest';
const MISTRAL_MODEL_NAME = 'Mistral Small 4';

test.describe('CLI default model settings contract', () => {
	test.setTimeout(180_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// contract-test: supporting surface=cli assertions=ai-model-routing.preferences.exclusive-tier-defaults,ai-model-routing.precedence.chat-over-tier-over-auto
	test('settings ai models set-defaults controls chat model routing', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const chatIds: string[] = [];

		const setDefaults = async (value: string, allBuckets = false) => {
			const flags = ['--simple', value];
			if (allBuckets) flags.push('--complex', value, '--most-demanding', value);
			const result = await runCli(
				apiUrl,
				['settings', 'ai', 'models', 'set-defaults', ...flags, '--json'],
				30_000
			);
			expectCliSuccess(result, `set ${allBuckets ? 'all saved model defaults' : 'simple default'} to ${value}`);
			const parsed = parseCliJson(result);
			expect(parsed.success).toBe(true);
		};

		const sendQuestion = async (fixtureId: string): Promise<any> => {
			const result = await runCli(
				apiUrl,
				['chats', 'new', withMockMarker('Capital of Germany?', fixtureId), '--json'],
				75_000
			);
			expectCliSuccess(result, `chat send ${fixtureId}`);
			const parsed = parseCliJson(result);
			if (parsed.chatId) chatIds.push(parsed.chatId);
			return parsed;
		};

		try {
			// All three existing settings flags remain accepted with four routing levels.
			await setDefaults(MISTRAL_MODEL_ID, true);
			const pinned = await sendQuestion('default_model_mistral');
			if (typeof pinned.modelName !== 'string') {
				throw new Error(`Pinned CLI output omitted modelName: ${JSON.stringify(pinned, null, 2)}`);
			}
			expect(pinned.modelName).toContain(MISTRAL_MODEL_NAME);

			await setDefaults('auto');
			const auto = await sendQuestion('default_model_auto');
			expect(String(auto.modelName || '').toLowerCase()).not.toContain(
				MISTRAL_MODEL_NAME.toLowerCase()
			);
		} finally {
			await setDefaults('auto', true).catch((error: Error) => {
				console.warn(`[default-model-cli] Failed to reset model defaults: ${error.message}`);
			});
			for (const chatId of chatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 15_000);
			}
		}
	});
});
