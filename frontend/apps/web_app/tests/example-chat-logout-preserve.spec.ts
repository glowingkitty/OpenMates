/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression coverage for public example chats during logout cleanup.
 * Static example chats are the same for every user, so logout/session-expiry
 * cleanup must clear private user state without clearing the open example chat.
 * This spec avoids fullscreen/embed interactions so it isolates the logout bug.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');

async function expectExampleChatVisible(page: any) {
	await expect(page).toHaveURL(/#chat-id=example-gigantic-airplanes/, { timeout: 15000 });
	await expect(page.getByTestId('user-message-content').filter({
		hasText: 'rocket'
	})).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('message-assistant').filter({
		hasText: 'Beluga'
	})).toBeVisible({ timeout: 15000 });
	await expect(page.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"][data-status="finished"]').first()).toBeVisible({ timeout: 15000 });
}

test.describe('Example chat logout preservation', () => {
	// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('keeps a static example chat open when logout cleanup runs', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto('/example/gigantic-airplanes-transporting-rocket-parts', {
			waitUntil: 'domcontentloaded'
		});
		await expectExampleChatVisible(page);

		await page.evaluate(() => {
			window.dispatchEvent(new CustomEvent('userLoggingOut'));
		});

		await expectExampleChatVisible(page);
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').first()).not.toBeVisible({ timeout: 5000 });
	});
});
