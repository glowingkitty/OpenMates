/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.catalog.capability-recommendation-variants
test('Claude and OpenAI selectors expose only the curated models', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, email, password, otpKey);

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl) throw new Error('The isolated API URL is required to verify model availability.');
	const catalogueResponse = await page.request.get(`${apiUrl}/v1/models`);
	expect(catalogueResponse.ok()).toBe(true);
	const catalogue = (await catalogueResponse.json()).data;
	const allowed: Record<string, string[]> = {
		anthropic: ['claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
		openai: ['gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-luna', 'gpt-5.6-terra', 'gpt-oss-120b']
	};
	for (const model of catalogue) {
		if (allowed[model.owned_by]) {
			expect(allowed[model.owned_by]).toContain(model.id.split('/')[1]);
		}
	}
	for (const retired of ['anthropic/claude-haiku-4-5-20251001', 'anthropic/claude-sonnet-5', 'openai/gpt-6-sol']) {
		const response = await page.request.get(`${apiUrl}/v1/models/${retired}`);
		expect(response.status()).toBe(404);
		expect((await response.json()).error.code).toBe('model_not_found');
	}

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

	await expect(menu.getByTestId('composer-model-name')).toHaveText([
		'GPT-6.1 Sol', 'GPT-6 Luna', 'GPT-6 Astra', 'GPT-5.6 Terra', 'GPT-OSS-120b'
	]);
	const firstRow = menu.getByTestId('composer-model-row').first();
	await expect(firstRow.getByTestId('composer-model-name')).toHaveText('GPT-6.1 Sol');
	await expect(firstRow.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'high');
	await firstRow.getByTestId('composer-model-toggle').click();
	await expect(selector).toHaveAttribute('aria-label', /Model selection: GPT-6\.1 Sol/i);

	await selector.click();
	await menu.getByTestId('composer-model-back').click();
	await menu.getByTestId('composer-model-provider-anthropic').click();
	await expect(menu.getByTestId('composer-model-name')).toHaveText([
		'Claude Haiku 5.5', 'Claude Sonnet 5.5', 'Claude Opus 5.5', 'Claude Fable 5.1'
	]);
	for (const [name, level, capability] of [
		['Claude Haiku 5.5', 'low', 'Low'], ['Claude Sonnet 5.5', 'medium', 'Medium'],
		['Claude Opus 5.5', 'high', 'High'], ['Claude Fable 5.1', 'max', 'Maximum']
	]) {
		const row = menu.getByTestId('composer-model-row').filter({ hasText: name });
		await expect(row.getByTestId('composer-model-capability')).toHaveAttribute('data-level', level);
		await row.getByTestId('composer-model-toggle').click();
		await expect(selector.getByTestId('composer-model-selector-label')).toHaveText(name);
		await expect(selector.getByTestId('composer-model-selector-capability')).toHaveAttribute('data-level', level);
		await expect(selector).toHaveAttribute('aria-label', `Model selection: ${name}, ${name}, ${capability} capability`);
		await selector.click();
	}
	await menu.getByTestId('composer-model-back').click();
	await menu.getByTestId('composer-model-provider-mistral').click();
	const large = menu.getByTestId('composer-model-row').filter({ hasText: 'Mistral Large 4' });
	await expect(large.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'high');
	await large.getByTestId('composer-model-toggle').click();
	await expect(selector.getByTestId('composer-model-selector-label')).toHaveText('Mistral Large 4');
	await expect(selector.getByTestId('composer-model-selector-capability')).toHaveAttribute('data-level', 'high');
	await expect(selector).toHaveAttribute('aria-label', 'Model selection: Mistral Large 4, Mistral Large 4, High capability');
});
