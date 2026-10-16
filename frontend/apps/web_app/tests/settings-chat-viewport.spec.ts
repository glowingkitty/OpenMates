// playwright-account: not_required reason=public_guest_settings
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

type Layout = {
	chatTop: number;
	chatHeight: number;
	chatBottom: number;
	composerTop: number;
	composerBottom: number;
	mainBottom: number;
	documentBottom: number;
	viewportHeight: number;
};

async function layout(page: Page): Promise<Layout> {
	return page.evaluate(() => {
		const chat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
		const composer = document.querySelector<HTMLElement>('[data-testid="message-input-wrapper"]');
		const main = document.querySelector<HTMLElement>('.main-content');
		if (!chat || !composer || !main) throw new Error('Chat viewport elements are missing');
		const chatRect = chat.getBoundingClientRect();
		const composerRect = composer.getBoundingClientRect();
		return {
			chatTop: chatRect.top,
			chatHeight: chatRect.height,
			chatBottom: chatRect.bottom,
			composerTop: composerRect.top,
			composerBottom: composerRect.bottom,
			mainBottom: main.getBoundingClientRect().bottom,
			documentBottom: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
			viewportHeight: window.innerHeight
		};
	});
}

async function stableBaseline(page: Page): Promise<Layout> {
	await expect.poll(async () => {
		const before = await layout(page);
		await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
		const after = await layout(page);
		return Math.max(
			Math.abs(after.chatTop - before.chatTop),
			Math.abs(after.chatHeight - before.chatHeight),
			Math.abs(after.composerTop - before.composerTop)
		);
	}, { message: 'Guest chat layout settles before baseline', timeout: 5000 }).toBeLessThanOrEqual(1);
	return layout(page);
}

async function expectBoundedLayout(page: Page, baseline: Layout, step: string): Promise<void> {
	await expect.poll(async () => {
		const current = await layout(page);
		return {
			chatTop: Math.abs(current.chatTop - baseline.chatTop) <= 1,
			chatHeight: Math.abs(current.chatHeight - baseline.chatHeight) <= 1,
			chatBottom: Math.abs(current.chatBottom - baseline.chatBottom) <= 1,
			composerTop: Math.abs(current.composerTop - baseline.composerTop) <= 1,
			composerWithinChat: current.composerBottom <= current.chatBottom + 1,
			mainWithinViewport: current.mainBottom <= current.viewportHeight + 1,
			documentWithinViewport: current.documentBottom <= current.viewportHeight + 1
		};
	}, { message: `Chat and composer remain fixed in viewport ${step}`, timeout: 5000 }).toEqual({
		chatTop: true,
		chatHeight: true,
		chatBottom: true,
		composerTop: true,
		composerWithinChat: true,
		mainWithinViewport: true,
		documentWithinViewport: true
	});
}

for (const chat of ['welcome', 'example-svelte-runes-docs'] as const) {
	for (const viewport of [{ name: 'laptop', width: 1440, height: 900 }, { name: 'phone', width: 390, height: 844 }, { name: 'short-laptop', width: 1440, height: 600 }]) {
		// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,message-input.layout.responsive-parity
		test(`${chat} chat stays viewport-bound while guest settings scroll on ${viewport.name}`, async ({ page }: { page: Page }) => {
			test.setTimeout(45000);
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			const route = chat === 'welcome' ? '/' : `/#chat-id=${chat}`;
			await page.goto(getE2EDebugUrl(route), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });

			if (chat === 'welcome') {
				await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
				await page.getByTestId('daily-inspiration-next').click();
				await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
			} else {
				await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chat, { timeout: 15000 });
				await expect(page.getByTestId('mate-message-content').last()).toContainText('Svelte', { timeout: 15000 });
			}

			await expect(page.getByTestId('message-input-wrapper')).toBeVisible();
			const baseline = await stableBaseline(page);
			await expectBoundedLayout(page, baseline, 'before opening settings');

			await page.getByTestId('profile-container').click();
			await expect(page.getByTestId('settings-menu')).toBeVisible();
			await expectBoundedLayout(page, baseline, 'after opening settings');

			await page.getByRole('menuitem', { name: /Interface/i }).first().click();
			await page.getByRole('menuitem', { name: /Language/i }).first().click();
			await expect(page.getByRole('menuitem', { name: /Deutsch/i }).first()).toBeVisible();
			await expectBoundedLayout(page, baseline, 'on Language settings');

			const content = page.locator('.settings-content-wrapper');
			await expect.poll(() => content.evaluate((element: HTMLElement) => element.scrollHeight > element.clientHeight)).toBe(true);
			await content.evaluate((element: HTMLElement) => { element.scrollTop = element.scrollHeight; });
			await expect.poll(() => content.evaluate((element: HTMLElement) => element.scrollTop)).toBeGreaterThan(0);
			await expectBoundedLayout(page, baseline, 'after scrolling Language settings');

			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).toBeHidden();
			await expectBoundedLayout(page, baseline, 'after closing settings');
		});
	}
}
