/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression coverage for leaving the login/signup interface as a guest.
 *
 * The guest should return to the new-chat welcome screen, not the
 * for-everyone intro chat, and the chat list should remain closed by default.
 * Uses only public guest UI state; no credentials are required.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

async function expectNewChatWithClosedSidebar(page: any): Promise<void> {
	await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('chat-item-wrapper').first()).toBeHidden({ timeout: 3000 });

	const hash = await page.evaluate(() => window.location.hash);
	expect(hash).not.toContain('demo-for-everyone');
}

test.describe('Auth back to demo', () => {
	test('returns from signup and login to new chat with chats list closed', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 1440, height: 900 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expectNewChatWithClosedSidebar(page);

		await openSignupInterface(page);
		await expect(page.getByTestId('login-wrapper')).toBeVisible({ timeout: 10000 });
		await page.getByRole('button', { name: /^Demo$/ }).first().click();
		await expectNewChatWithClosedSidebar(page);

		await openSignupInterface(page);
		await expect(page.getByTestId('tab-login')).toBeVisible({ timeout: 10000 });
		await page.getByTestId('tab-login').click();
		await page.getByRole('button', { name: /^Demo$/ }).first().click();
		await expectNewChatWithClosedSidebar(page);
	});
});
