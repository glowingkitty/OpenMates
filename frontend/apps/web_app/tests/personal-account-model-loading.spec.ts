/* eslint-disable @typescript-eslint/no-require-imports */
/*
 * Authenticated account-health regression for reported issue 4NPP9.
 * Persists an exact model, reloads the same chat, and verifies account-scoped
 * restoration completes without a retry notification or permanently loading
 * model selector. This reproduces the delayed restore race from issue XW4UW.
 * proof-video: not_required reason=account_health
 */

export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const TEST_CREDENTIALS = {
	email: process.env.OPENMATES_TEST_ACCOUNT_EMAIL || '',
	password: process.env.OPENMATES_TEST_ACCOUNT_PASSWORD || '',
	otpKey: process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY || ''
};

// contract-test: supporting surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test('authenticated account loads its chat model selector without retry errors', async ({ page }) => {
	test.setTimeout(180000);
	expect(TEST_CREDENTIALS.email).not.toBe('');
	expect(TEST_CREDENTIALS.password).not.toBe('');
	expect(TEST_CREDENTIALS.otpKey).not.toBe('');

	const logCheckpoint = createSignupLogger('PERSONAL_ACCOUNT_MODEL_LOADING');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'personal-account-model-loading'
	});
	attachConsoleListeners(page, logCheckpoint);
	attachNetworkListeners(page, logCheckpoint);

	await page.addInitScript(() => {
		(window as any).__issue4NPP9Notifications = [];
		document.addEventListener('DOMContentLoaded', () => {
			const recordNotifications = (): void => {
				for (const element of document.querySelectorAll('[data-testid="notification"]')) {
					const text = element.textContent?.trim();
					if (text && !(window as any).__issue4NPP9Notifications.includes(text)) {
						(window as any).__issue4NPP9Notifications.push(text);
					}
				}
			};
			new MutationObserver(recordNotifications).observe(document.body, { childList: true, subtree: true });
			recordNotifications();
		});
	});

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot, {
		credentials: TEST_CREDENTIALS,
		waitForEditor: false
	});

	const activeChat = page.getByTestId('active-chat-container');
	const continueCard = page
		.getByTestId('recent-chats-scroll-container')
		.first()
		.getByRole('button')
		.first();
	await expect(continueCard).toBeVisible({ timeout: 60000 });
	await continueCard.click();
	await expect(activeChat).toHaveAttribute('data-current-chat-id', /.+/, { timeout: 60000 });

	const composer = activeChat.getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 60000 });
	await editor.click();

	const selector = composer.getByTestId('composer-model-selector');
	await expect(selector).toBeVisible({ timeout: 30000 });
	await expect(selector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	await expect(composer.getByTestId('composer-model-selector-label')).not.toHaveText('Loading...');

	await selector.click();
	const selectorMenu = composer.getByTestId('composer-model-selector-menu');
	await expect(selectorMenu).toBeVisible();
	await selectorMenu.getByTestId('composer-model-provider-openai').click();
	await selectorMenu.getByTestId('composer-model-row').first().getByTestId('composer-model-toggle').click();
	await expect(selector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	const selectedLabel = composer.getByTestId('composer-model-selector-label');
	await expect(selectedLabel).not.toHaveText('Auto select');
	const persistedModelLabel = await selectedLabel.textContent();
	expect(persistedModelLabel).toBeTruthy();

	const persistedChatId = await activeChat.getAttribute('data-current-chat-id');
	expect(persistedChatId).toBeTruthy();
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(activeChat).toHaveAttribute('data-current-chat-id', persistedChatId!, { timeout: 60000 });

	const restoredComposer = activeChat.getByTestId('message-field').last();
	await expect(restoredComposer.getByTestId('message-editor')).toBeVisible({ timeout: 60000 });
	await restoredComposer.getByTestId('message-editor').click();
	const restoredSelector = restoredComposer.getByTestId('composer-model-selector');
	await expect(restoredSelector).toBeVisible({ timeout: 30000 });
	await expect(restoredSelector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	const restoredLabel = restoredComposer.getByTestId('composer-model-selector-label');
	await expect(restoredLabel).toHaveText(persistedModelLabel!);
	await takeStepScreenshot(page, 'model-selector-restored');

	const notifications = await page.evaluate(() => (window as any).__issue4NPP9Notifications as string[]);
	expect(notifications.filter((message) => message.trim().toLowerCase() === 'try again')).toEqual([]);

	await restoredSelector.click();
	await restoredComposer.getByTestId('composer-model-selector-menu').getByTestId('composer-model-auto').click();
	await expect(restoredSelector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	await expect(restoredLabel).toHaveText('Auto select');
});
