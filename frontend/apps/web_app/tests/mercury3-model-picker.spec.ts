/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.catalog.capability-recommendation-variants
test('Mercury 3 is manually selectable through Inception with medium capability', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, email, password, otpKey);

	const log = createSignupLogger('MERCURY3_MODEL_PICKER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'mercury3-model-picker' });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible()) {
		await sidebar.getByRole('button', { name: 'Close', exact: true }).click();
	}
	await expect(sidebar).not.toBeVisible();

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
	await menu.getByTestId('composer-model-show-more').click();
	const inception = menu.getByTestId('composer-model-provider-inception');
	await expect(inception.getByTestId('composer-model-provider-label').locator('strong')).toHaveText('Inception');
	const providerIcon = inception.getByTestId('composer-model-provider-icon');
	// Vite inlines this small SVG in production builds; development serves the file URL.
	await expect(providerIcon).toHaveAttribute('src', /^(?:data:image\/svg\+xml[;,]|.*\/inception(?:[.-][\w-]+)?\.svg(?:\?|$))/);
	await expect.poll(() => providerIcon.evaluate((icon: HTMLImageElement) => icon.complete && icon.naturalWidth > 0)).toBe(true);
	const inceptionIconSrc = await providerIcon.getAttribute('src');
	await inception.click();

	const mercury = menu.getByTestId('composer-model-row').filter({
		has: page.getByTestId('composer-model-name').locator('strong').filter({ hasText: /^Mercury 3$/ })
	});
	await expect(mercury).toHaveCount(1);
	await expect(mercury.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'medium');
	const modelIcon = mercury.getByTestId('composer-model-icon').locator('img');
	await expect(modelIcon).toHaveAttribute('src', inceptionIconSrc);
	await expect.poll(() => modelIcon.evaluate((icon: HTMLImageElement) => icon.complete && icon.naturalWidth > 0)).toBe(true);
	await screenshot(page, 'inception-mercury3-available');

	// Change only this unsent draft's selection; no inference or account-default write.
	await mercury.getByTestId('composer-model-toggle').click();
	await expect(menu).not.toBeVisible();
	await expect(selector.getByTestId('composer-model-selector-label')).toHaveText('Mercury 3');
	await expect(selector.getByTestId('composer-model-selector-capability')).toHaveAttribute('data-level', 'medium');
	await expect(selector).toHaveAttribute('aria-label', 'Model selection: Mercury 3, Mercury 3, Medium capability');
	await screenshot(page, 'mercury3-selected');

	// Reopening must return to the exact selected model's provider with its toggle checked.
	await selector.click();
	await expect(mercury.getByRole('checkbox', { name: 'Mercury 3', exact: true })).toBeChecked();
	await menu.getByTestId('composer-model-back').click();
	await menu.getByTestId('composer-model-auto').click();
	await expect(selector.getByTestId('composer-model-selector-label')).toHaveText('Auto select');
	await expect(menu).not.toBeVisible();
});
