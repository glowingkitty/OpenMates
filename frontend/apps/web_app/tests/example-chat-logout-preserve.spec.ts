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
	await expect(page).toHaveURL(/#chat-id=example-printable-benchy-phone-stand/, { timeout: 15000 });
	await expect(page.getByTestId('user-message-content').filter({
		hasText: 'Find 3D-printable Benchy and phone stand models on Printables'
	})).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('message-assistant').filter({
		hasText: 'The 3DBenchy Collection'
	})).toBeVisible({ timeout: 15000 });
	await expect(page.locator('[data-testid="embed-preview"][data-app-id="models3d"][data-skill-id="search"][data-status="finished"]').first()).toBeVisible({ timeout: 15000 });
}

test.describe('Example chat logout preservation', () => {
	test('keeps a static example chat open when logout cleanup runs', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto('/example/printable-benchy-phone-stand-models', {
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
