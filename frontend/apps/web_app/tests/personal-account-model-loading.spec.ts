/* eslint-disable @typescript-eslint/no-require-imports */
/*
 * Authenticated account-health regression for reported issue 4NPP9.
 * Opens a persisted chat because account-scoped model preference restoration
 * does not run on the new-chat welcome surface. Verifies restoration completes
 * without the retry notification or a permanently loading model selector.
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
	await expect(composer.getByTestId('composer-model-selector-menu')).toBeVisible();
	await takeStepScreenshot(page, 'model-selector-loaded');

	const notifications = await page.evaluate(() => (window as any).__issue4NPP9Notifications as string[]);
	expect(notifications.filter((message) => message.trim().toLowerCase() === 'try again')).toEqual([]);
});
