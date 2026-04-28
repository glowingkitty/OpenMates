/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Regression guard for ChatHeader navigation order.
 *
 * The header controls must navigate through chats in the exact order rendered
 * by Chats.svelte. The right-side control and a right-to-left swipe both move
 * to the previous item in that sidebar order; the left-side control and reverse
 * swipe move to the next item.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

async function ensureSidebarOpen(page: any): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (await activityHistory.isVisible().catch(() => false)) return;

	await page.getByTestId('sidebar-toggle').click();
	await expect(activityHistory).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(1000);
}

async function ensureSidebarClosed(page: any): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (!(await activityHistory.isVisible().catch(() => false))) return;

	await page.getByTestId('sidebar-toggle').click();
	await expect(activityHistory).not.toBeVisible({ timeout: 10000 });
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
		touches: [{ clientX: startX, clientY: 80 }]
	});
	await header.dispatchEvent('touchmove', {
		touches: [{ clientX: endX, clientY: 84 }]
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
				nodes.map((node) => (node.textContent || '').trim()).filter(Boolean).slice(0, 3)
			);

		expect(orderedTitles.length).toBeGreaterThanOrEqual(3);
		const [previousTitle, selectedTitle, nextTitle] = orderedTitles;

		await chatItems.nth(1).click();
		await expectHeaderTitle(page, selectedTitle);
		await ensureSidebarClosed(page);

		await page.getByTestId('chat-header-previous').click();
		await expectHeaderTitle(page, previousTitle);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, selectedTitle);

		await swipeHeader(page, 360, 240);
		await expectHeaderTitle(page, previousTitle);

		await swipeHeader(page, 240, 360);
		await expectHeaderTitle(page, selectedTitle);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, nextTitle);
	});
});
