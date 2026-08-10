/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chat settings usage regression tests.
 *
 * Verifies that guest-accessible static example chats can show real historical
 * usage costs when the generated example data includes static usage_entries.
 * The flow stays unauthenticated and must not depend on private usage APIs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Example chat settings usage', () => {
	test('guest example chat with static usage exposes usage tab and rows', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-berlin-morning-bike-forecast';

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('chat-details-button')).toBeVisible({ timeout: 10000 });

		await page.getByTestId('chat-details-button').click();
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu.getByTestId('chat-settings-tab-share')).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu.getByTestId('chat-settings-tab-usage')).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu.getByTestId('chat-settings-tab-plan')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('chat-settings-tab-tasks')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('chat-settings-tab-files')).toHaveCount(0);

		await settingsMenu.getByTestId('chat-settings-tab-usage').click();
		await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${exampleChatId}`, {
			timeout: 10000
		});
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-usage')).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(/25\s*credits/i);
		await expect(settingsMenu.getByTestId('chat-settings-usage-row')).toHaveCount(2);
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('ai | ask');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('Google AI Studio / US');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('24');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').nth(1)).toContainText('weather | forecast');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').nth(1)).toContainText('1');
	});
});
