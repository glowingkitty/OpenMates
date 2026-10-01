/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.catalog.capability-recommendation-variants
test('GPT-6.1 Sol is the newest selectable OpenAI model', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, email, password, otpKey);

	const log = createSignupLogger('GPT61_SOL_MODEL_PICKER');
	await loginToTestAccount(page, log, createStepScreenshotter(log, { filenamePrefix: 'gpt61-sol-model-picker' }));
	await startNewChat(page, log);

	const composer = page.getByTestId('active-chat-container').getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	const selector = composer.getByTestId('composer-model-selector');
	await expect(selector).toBeVisible({ timeout: 10000 });
	await selector.click();
	const menu = composer.getByTestId('composer-model-selector-menu');
	await menu.getByTestId('composer-model-provider-openai').click();

	const firstRow = menu.getByTestId('composer-model-row').first();
	await expect(firstRow.getByTestId('composer-model-name')).toHaveText('GPT-6.1 Sol');
	await expect(firstRow.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'high');
	await firstRow.getByTestId('composer-model-toggle').click();
	await expect(selector).toHaveAttribute('aria-label', /Model selection: GPT-6\.1 Sol/i);
});
