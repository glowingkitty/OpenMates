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

const MISTRAL_MODEL_ID = 'mistral/mistral-small-2506';
const MISTRAL_MODEL_NAME = 'Mistral Small 3.2';

test.describe('CLI default model settings contract', () => {
	test.setTimeout(180_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('settings ai models set-defaults controls chat model routing', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const chatIds: string[] = [];

		const setSimpleDefault = async (value: string) => {
			const result = await runCli(
				apiUrl,
				['settings', 'ai', 'models', 'set-defaults', '--simple', value, '--json'],
				30_000
			);
			expectCliSuccess(result, `set simple default to ${value}`);
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
			await setSimpleDefault(MISTRAL_MODEL_ID);
			const pinned = await sendQuestion('default_model_mistral');
			expect(pinned.modelName).toContain(MISTRAL_MODEL_NAME);

			await setSimpleDefault('auto');
			const auto = await sendQuestion('default_model_auto');
			expect(String(auto.modelName || '').toLowerCase()).not.toContain(
				MISTRAL_MODEL_NAME.toLowerCase()
			);
		} finally {
			await setSimpleDefault('auto').catch((error: Error) => {
				console.warn(`[default-model-cli] Failed to reset simple default: ${error.message}`);
			});
			for (const chatId of chatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 15_000);
			}
		}
	});
});
