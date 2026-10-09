/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const retiredStoryIds = [
	'openmates-intro',
	'openmates-actionable-events',
	'openmates-privacy-safety',
	'openmates-mates-focus',
	'openmates-provider-cross-platform',
	'openmates-signup-cta'
];

async function openGuestWelcome(page: any) {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
}

test.describe('Signed-out new-chat welcome', () => {
	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,daily-inspiration.guest-isolated
	test('uses ordinary inspirations and welcome controls without promotional stories', async ({ page }: { page: any }) => {
		await openGuestWelcome(page);
		await expect(page.getByTestId('message-editor')).toBeVisible();
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible();
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect(page.getByTestId('guest-slide-content')).toHaveCount(0);
		const bannerId = await page.getByTestId('daily-inspiration-banner').getAttribute('data-current-inspiration-id');
		expect(bannerId).toBeTruthy();
		expect(retiredStoryIds).not.toContain(bannerId);
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.guest-examples,landing-onboarding.uses-real-chat-shell
	test('shows all real example chats and returns to a blank new chat', async ({ page }: { page: any }) => {
		await openGuestWelcome(page);
		await page.getByTestId('guest-show-all-examples').click();
		const grid = page.getByTestId('guest-all-examples-grid');
		await expect(grid).toBeVisible();
		const cards = grid.locator('[data-chat-id^="example-"]');
		await expect.poll(() => cards.count()).toBeGreaterThan(1);
		const realChatId = await cards.first().getAttribute('data-chat-id');
		await cards.first().click();
		await expect.poll(() => page.evaluate(() => window.location.hash)).toContain(realChatId);
		const newChatButton = page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
		await expect(newChatButton).toBeVisible();
		await newChatButton.click();
		await expect(page.getByTestId('message-editor')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect.poll(() => page.evaluate(() => window.location.hash)).not.toContain('chat-id=');
	});
});
