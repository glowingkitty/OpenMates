/* eslint-disable @typescript-eslint/no-require-imports */
/*
 * Account-health regression for reported issue 4NPP9.
 * Uses only the configured base personal test-account credentials.
 * Verifies login and real-chat hydration never surface the retry notification
 * and that the composer model selector leaves its loading state.
 * proof-video: not_required reason=account_health
 */

export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const EXPECTED_EMAIL = 'jan41139@openmates.org';
const PERSONAL_CREDENTIALS = {
	email: process.env.OPENMATES_TEST_ACCOUNT_EMAIL || '',
	password: process.env.OPENMATES_TEST_ACCOUNT_PASSWORD || '',
	otpKey: process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY || ''
};

// contract-test: supporting surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test('personal dev account loads its chat model selector without retry errors', async ({ page }) => {
	test.setTimeout(180000);
	expect(PERSONAL_CREDENTIALS.email.toLowerCase()).toBe(EXPECTED_EMAIL);
	expect(PERSONAL_CREDENTIALS.password).not.toBe('');
	expect(PERSONAL_CREDENTIALS.otpKey).not.toBe('');

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
		credentials: PERSONAL_CREDENTIALS,
		waitForEditor: true
	});

	const activeChat = page.getByTestId('active-chat-container');
	const composer = activeChat.getByTestId('message-field').last();
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
