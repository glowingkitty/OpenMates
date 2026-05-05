/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Regression guard for ChatHeader navigation order.
 *
 * The header controls navigate through the newest-first chat order rendered by
 * Chats.svelte. The right-side control and a right-to-left swipe move to the
 * previous recent chat (older item); the left-side control and reverse swipe
 * move back toward newer items.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const INTRO_CHAT_TITLES = new Set([
	'OpenMates | For everyone',
	'OpenMates | For developers',
	'Who develops OpenMates?'
]);

async function ensureSidebarOpen(page: any): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (await activityHistory.isVisible().catch(() => false)) return;

	await page.getByTestId('sidebar-toggle').click();
	await expect(activityHistory).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(1000);
}

async function expectHeaderTitle(page: any, expectedTitle: string): Promise<void> {
	const headerTitle = page.getByTestId('chat-header-title');
	await expect(headerTitle).toBeVisible({ timeout: 12000 });
	await expect(headerTitle).toHaveText(expectedTitle, { timeout: 12000 });
	expect(await page.evaluate(() => window.location.hash.includes('chat-id='))).toBe(true);
}

async function swipeHeader(page: any, startX: number, endX: number): Promise<void> {
	const header = page.locator('.chat-header-banner');
	await expect(header).toBeVisible({ timeout: 10000 });
	await header.dispatchEvent('touchstart', {
		touches: [{ identifier: 1, clientX: startX, clientY: 80 }]
	});
	await header.dispatchEvent('touchmove', {
		touches: [{ identifier: 1, clientX: endX, clientY: 84 }]
	});
	await header.dispatchEvent('touchend', { touches: [] });
}

test.describe('ChatHeader follows Chats.svelte order', () => {
	test('right control and right-to-left swipe navigate to previous sidebar chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 1280, height: 900 });
		await page.goto(getE2EDebugUrl('/?lang=en'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('chat-id='), null, {
			timeout: 15000
		});

		await ensureSidebarOpen(page);

		const chatItems = page.getByTestId('chat-item-wrapper');
		await expect(chatItems.nth(2)).toBeVisible({ timeout: 15000 });
		const orderedTitles = await chatItems
			.locator('[data-testid="chat-title"]')
			.evaluateAll((nodes: Element[]) =>
				nodes.map((node) => (node.textContent || '').trim()).filter(Boolean)
			);

		const selectedIndex = orderedTitles.findIndex((title: string, index: number, titles: string[]) => {
			if (index === 0 || index === titles.length - 1) return false;
			return [titles[index - 1], title, titles[index + 1]].every(
				(candidate) => !INTRO_CHAT_TITLES.has(candidate)
			);
		});

		expect(selectedIndex).toBeGreaterThan(0);
		const newerTitle = orderedTitles[selectedIndex - 1];
		const selectedTitle = orderedTitles[selectedIndex];
		const olderTitle = orderedTitles[selectedIndex + 1];

		await chatItems.nth(selectedIndex).click();
		await expectHeaderTitle(page, selectedTitle);

		await page.getByTestId('chat-header-previous').click();
		await expectHeaderTitle(page, olderTitle);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, selectedTitle);

		await swipeHeader(page, 360, 240);
		await expectHeaderTitle(page, olderTitle);

		await swipeHeader(page, 240, 360);
		await expectHeaderTitle(page, selectedTitle);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, newerTitle);
	});
});
