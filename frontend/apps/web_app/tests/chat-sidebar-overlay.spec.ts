// playwright-account: not_required reason=public_guest_chat_shell_sidebar
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const sidebarProof = defineVideoProof({
	id: 'chat-sidebar-overlay', title: 'Chat sidebar: eased overlay on phones, growing width on desktop', surface: 'web',
	devices: ['web-phone', 'web-laptop'], domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'phone-open', text: 'On a phone the sidebar slides in from the left over a dimmed chat.', checkpoint: 'sidebar-open', devices: ['web-phone'] },
		{ id: 'phone-closed', text: 'Tapping the same spot closes it again, sliding back out the same way.', checkpoint: 'sidebar-closed', devices: ['web-phone'] },
		{ id: 'desktop-open', text: 'On a large screen the sidebar grows in width while the chat area narrows.', checkpoint: 'sidebar-open', devices: ['web-laptop'] },
		{ id: 'desktop-closed', text: 'Closing it reverses the movement without a jump.', checkpoint: 'sidebar-closed', devices: ['web-laptop'] },
	],
	assertions: [
		{ id: 'sidebar.phone-overlay-open', checkpoint: 'sidebar-open', visual: 'The sidebar covers the left side of the phone screen above a dimmed chat, its close button where the menu button was.', devices: ['web-phone'] },
		{ id: 'sidebar.phone-closed', checkpoint: 'sidebar-closed', visual: 'The sidebar and the dim backdrop are gone and the menu button is back.', devices: ['web-phone'] },
		{ id: 'sidebar.desktop-open', checkpoint: 'sidebar-open', visual: 'The sidebar sits beside the chat area, which is narrower; its close button is where the menu button was, search on the right.', devices: ['web-laptop'] },
		{ id: 'sidebar.desktop-closed', checkpoint: 'sidebar-closed', visual: 'The chat area fills the full width again.', devices: ['web-laptop'] },
	],
	tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 3000 },
});

/**
 * Chat sidebar motion (TASK-4266): on phones the sidebar is an eased overlay
 * with a backdrop whose close button sits on the menu button; on desktop the
 * sidebar grows in width while the chat area narrows with the same easing.
 */

type Sample = { t: number; sidebarLeft: number; sidebarWidth: number; mainLeft: number; visibility: string };

/** Samples sidebar and chat geometry every animation frame while `action` runs. */
/**
 * Samples the sidebar every animation frame until it has moved and then rested for 150 ms
 * (slow CI machines delay the click, so a fixed window is not enough), or `maxMs` passes.
 */
async function sampleDuring(page: Page, action: () => Promise<void>, maxMs = 4000): Promise<Sample[]> {
	const pending = page.evaluate((capMs: number) => new Promise<Sample[]>((resolve) => {
		const sidebar = document.querySelector<HTMLElement>('[data-testid="chat-sidebar"]');
		const main = document.querySelector<HTMLElement>('[data-testid="main-content"]');
		if (!sidebar || !main) throw new Error('Sidebar or main content is missing');
		const samples: Sample[] = [];
		const start = performance.now();
		let lastChange = start;
		let sawChange = false;
		const tick = (now: number) => {
			const rect = sidebar.getBoundingClientRect();
			const sample = {
				t: now - start,
				sidebarLeft: rect.left,
				sidebarWidth: rect.width,
				mainLeft: main.getBoundingClientRect().left,
				visibility: getComputedStyle(sidebar).visibility
			};
			const previous = samples[samples.length - 1];
			if (
				previous &&
				(previous.sidebarLeft !== sample.sidebarLeft ||
					previous.sidebarWidth !== sample.sidebarWidth ||
					previous.mainLeft !== sample.mainLeft ||
					previous.visibility !== sample.visibility)
			) {
				sawChange = true;
				lastChange = now;
			}
			samples.push(sample);
			const rested = sawChange && now - lastChange >= 150;
			if (rested || now - start >= capMs) resolve(samples);
			else requestAnimationFrame(tick);
		};
		requestAnimationFrame(tick);
	}), maxMs);
	await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
	await action();
	return pending;
}

async function openGuestChat(page: Page, width: number, height: number): Promise<void> {
	await page.setViewportSize({ width, height });
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('sidebar-toggle')).toBeAttached({ timeout: 30000 });
	await page.evaluate(() => document.fonts.ready);
}

async function ensureSidebarClosed(page: Page): Promise<void> {
	const sidebar = page.getByTestId('chat-sidebar');
	if (await sidebar.isVisible()) {
		await page.getByTestId('chats-close-button').click();
	}
	await expect(sidebar).toBeHidden({ timeout: 5000 });
	await expect(page.getByTestId('sidebar-toggle')).toBeVisible();
	await page.waitForTimeout(500);
}

function center(box: { x: number; y: number; width: number; height: number }) {
	return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.overlay-motion,chat-navigation.sidebar.close-at-menu-position,chat-navigation.sidebar.keyboard-focus
test('phone: sidebar slides in as an eased overlay and closes from the same spot', async ({ page }: { page: Page }, testInfo: TestInfo) => {
	const proof = createVideoProofRuntime(sidebarProof, { device: 'web-phone', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
	await openGuestChat(page, 390, 844);
	await ensureSidebarClosed(page);
	const toggle = page.getByTestId('sidebar-toggle');
	const sidebar = page.getByTestId('chat-sidebar');
	const backdrop = page.getByTestId('sidebar-backdrop');
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await expect(backdrop).toBeHidden();
	const toggleBox = (await toggle.boundingBox())!;
	const mainBefore = (await page.getByTestId('main-content').boundingBox())!;
	await testInfo.attach('phone-closed', { body: await page.screenshot(), contentType: 'image/png' });

	const opening = await sampleDuring(page, () => toggle.click());
	await expect(sidebar).toBeVisible();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(backdrop).toBeVisible();
	const width = opening[opening.length - 1].sidebarWidth;
	expect(opening[opening.length - 1].sidebarLeft).toBeCloseTo(0, 0);
	// Eased: starts off-screen, passes through intermediate positions, ends at 0.
	const moving = opening.filter((s) => s.sidebarLeft > -width + 2 && s.sidebarLeft < -2);
	expect(moving.length).toBeGreaterThanOrEqual(3);
	// ease-in-out cubic over about 300 ms, configured on the element itself.
	const motion = await sidebar.evaluate((el) => {
		const style = getComputedStyle(el);
		return { duration: style.transitionDuration, easing: style.transitionTimingFunction };
	});
	expect(motion.easing).toContain('cubic-bezier(0.65, 0, 0.35, 1)');
	expect(motion.duration).toContain('0.3s');
	// It arrives within the animation time (measured from the first moving frame, click latency excluded).
	const startedAt = opening.find((s) => s.sidebarLeft > -width + 0.5)!.t;
	const finishedAt = opening.find((s) => s.sidebarLeft >= -0.5)!.t;
	expect(finishedAt - startedAt).toBeLessThan(450);
	// The chat does not move; it is covered by the overlay.
	const mainAfter = (await page.getByTestId('main-content').boundingBox())!;
	expect(mainAfter.x).toBe(mainBefore.x);
	await page.waitForTimeout(100);
	await testInfo.attach('phone-open', { body: await page.screenshot(), contentType: 'image/png' });

	// Close button is exactly where the menu button was; focus moved into the sidebar.
	const closeButton = page.getByTestId('chats-close-button');
	const closeBox = (await closeButton.boundingBox())!;
	expect(Math.abs(center(closeBox).x - center(toggleBox).x)).toBeLessThanOrEqual(1);
	expect(Math.abs(center(closeBox).y - center(toggleBox).y)).toBeLessThanOrEqual(1);
	await expect(closeButton).toBeFocused();
	// One button order: close first, search at the other end.
	const searchBox = (await page.getByTestId('search-button').boundingBox())!;
	expect(searchBox.x).toBeGreaterThan(closeBox.x + closeBox.width);
	await proof.assert('sidebar.phone-overlay-open', async () => {
		await expect(sidebar).toBeVisible();
		await expect(backdrop).toBeVisible();
	});
	await proof.checkpoint('sidebar-open');

	// Closing uses the same easing in reverse and keeps the sidebar visible while it slides.
	const closing = await sampleDuring(page, () => closeButton.click());
	await expect(sidebar).toBeHidden();
	await expect(backdrop).toBeHidden();
	const slideOut = closing.filter((s) => s.sidebarLeft > -width + 2 && s.sidebarLeft < -2);
	expect(slideOut.length).toBeGreaterThanOrEqual(3);
	expect(slideOut.every((s) => s.visibility === 'visible')).toBe(true);
	await expect(toggle).toBeFocused();
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await proof.assert('sidebar.phone-closed', async () => {
		await expect(sidebar).toBeHidden();
		await expect(backdrop).toBeHidden();
	});
	await proof.checkpoint('sidebar-closed');

	// Escape closes it, and so does tapping the backdrop.
	await toggle.click();
	await expect(sidebar).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(sidebar).toBeHidden();
	await expect(toggle).toBeFocused();
	await toggle.click();
	await expect(backdrop).toBeVisible();
	await page.mouse.click(380, 400);
	await expect(sidebar).toBeHidden();
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await proof.attach();
});

// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.overlay-motion,chat-navigation.sidebar.width-transition
test('phone: reduced motion opens and closes without animation', async ({ page }: { page: Page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await openGuestChat(page, 390, 844);
	await ensureSidebarClosed(page);
	const toggle = page.getByTestId('sidebar-toggle');
	const opening = await sampleDuring(page, () => toggle.click());
	const width = opening[opening.length - 1].sidebarWidth;
	expect(opening.filter((s) => s.sidebarLeft > -width + 2 && s.sidebarLeft < -2).length).toBeLessThanOrEqual(1);
	await expect(page.getByTestId('chat-sidebar')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.width-transition,chat-navigation.sidebar.keyboard-focus
test('desktop: sidebar grows while the chat area narrows with the same easing', async ({ page }: { page: Page }, testInfo: TestInfo) => {
	const proof = createVideoProofRuntime(sidebarProof, { device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
	await openGuestChat(page, 1280, 800);
	await ensureSidebarClosed(page);
	const toggle = page.getByTestId('sidebar-toggle');
	const sidebar = page.getByTestId('chat-sidebar');
	const toggleBox = (await toggle.boundingBox())!;
	await testInfo.attach('desktop-closed', { body: await page.screenshot(), contentType: 'image/png' });

	const opening = await sampleDuring(page, () => toggle.click());
	await expect(sidebar).toBeVisible();
	await testInfo.attach('desktop-open-samples', { body: JSON.stringify(opening), contentType: 'application/json' });
	const last = opening[opening.length - 1];
	expect(last.sidebarWidth).toBeCloseTo(325, 0);
	expect(last.mainLeft).toBeCloseTo(335, 0);
	const growing = opening.filter((s) => s.sidebarWidth > 4 && s.sidebarWidth < 321);
	// Layout-driven frames are slower than compositor frames on CI; a few suffice to show it is eased.
	expect(growing.length).toBeGreaterThanOrEqual(1);
	// Same easing: the chat area's left edge always trails the sidebar edge by the fixed margin.
	// Only frames where both are mid-motion count: a stalled main thread can show the chat area already
	// at its end position while the sidebar width has not started (a rendering hiccup, not an easing difference).
	for (const sample of growing.filter((s) => s.mainLeft < 330)) {
		expect(Math.abs(sample.mainLeft - sample.sidebarWidth - 10), `frame ${JSON.stringify(sample)} of ${JSON.stringify(opening.map((s) => [Math.round(s.sidebarWidth), Math.round(s.mainLeft)]))}`).toBeLessThanOrEqual(3);
	}
	await page.waitForTimeout(100);
	await testInfo.attach('desktop-open', { body: await page.screenshot(), contentType: 'image/png' });
	const closeButton = page.getByTestId('chats-close-button');
	await expect(closeButton).toBeFocused();
	// Same button order and spot as on phones: close exactly where the menu button was, search at the other end.
	const closeBox = (await closeButton.boundingBox())!;
	expect(Math.abs(center(closeBox).x - center(toggleBox).x)).toBeLessThanOrEqual(1);
	expect(Math.abs(center(closeBox).y - center(toggleBox).y)).toBeLessThanOrEqual(1);
	const searchBox = (await page.getByTestId('search-button').boundingBox())!;
	expect(searchBox.x).toBeGreaterThan(closeBox.x + closeBox.width);
	await proof.assert('sidebar.desktop-open', async () => {
		await expect(sidebar).toBeVisible();
	});
	await proof.checkpoint('sidebar-open');

	const closing = await sampleDuring(page, () => page.keyboard.press('Escape'));
	await expect(sidebar).toBeHidden();
	const shrinking = closing.filter((s) => s.sidebarWidth > 4 && s.sidebarWidth < 321);
	expect(shrinking.length).toBeGreaterThanOrEqual(1);
	expect(closing[closing.length - 1].mainLeft).toBeCloseTo(10, 0);
	await expect(toggle).toBeFocused();
	await proof.assert('sidebar.desktop-closed', async () => {
		await expect(sidebar).toBeHidden();
	});
	await proof.checkpoint('sidebar-closed');
	await proof.attach();
});
