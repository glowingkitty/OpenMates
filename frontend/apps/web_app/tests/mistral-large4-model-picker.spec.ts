/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.catalog.capability-recommendation-variants
test('Mistral selector reflects curated capabilities and visibility', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, email, password, otpKey);

	const log = createSignupLogger('MISTRAL_LARGE4_MODEL_PICKER');
	await loginToTestAccount(page, log, createStepScreenshotter(log, { filenamePrefix: 'mistral-large4-model-picker' }));
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
	await menu.getByTestId('composer-model-provider-mistral').click();
	for (const hiddenName of ['Ministral 3 8B', 'Mistral Small 3.2', 'Devstral 2']) {
		await expect(menu.getByTestId('composer-model-name').locator('strong').filter({ hasText: hiddenName })).toHaveCount(0);
	}
	for (const [name, level] of [
		[/^Mistral Large 4$/, 'high'],
		[/^Mistral Medium 3\.5$/, 'medium'],
		[/^Mistral Small 4$/, 'low'],
	] as const) {
		const row = menu.getByTestId('composer-model-row').filter({ has: page.getByTestId('composer-model-name').locator('strong').filter({ hasText: name }) });
		await expect(row.getByTestId('composer-model-capability')).toHaveAttribute('data-level', level);
	}

	const model = menu.getByTestId('composer-model-row').filter({ has: page.getByTestId('composer-model-name').locator('strong').filter({ hasText: /^Mistral Large 4$/ }) });
	await expect(model).toHaveCount(1);
	await expect(model.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'high');
	await model.getByTestId('composer-model-toggle').click();
	await expect(selector).toHaveAttribute('aria-label', /Model selection: Mistral Large 4/i);
});
