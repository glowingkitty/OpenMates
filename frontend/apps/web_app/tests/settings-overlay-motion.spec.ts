// playwright-account: not_required reason=public_guest_settings_overlay_shell
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const settingsProof = defineVideoProof({
	id: 'settings-overlay-motion', title: 'Settings menu: eased overlay from the right on small screens', surface: 'web',
	devices: ['web-phone', 'web-laptop'], domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'phone-open', text: 'On a phone the settings menu slides in from the right over a dimmed chat.', checkpoint: 'settings-open', devices: ['web-phone'] },
		{ id: 'phone-closed', text: 'The close button sits where the settings button was; tapping it slides the menu back out.', checkpoint: 'settings-closed', devices: ['web-phone'] },
		{ id: 'narrow-open', text: 'On a narrow desktop window the settings menu behaves the same way.', checkpoint: 'settings-open', devices: ['web-laptop'] },
		{ id: 'narrow-closed', text: 'Closing it reverses the movement and fades the backdrop out.', checkpoint: 'settings-closed', devices: ['web-laptop'] },
	],
	assertions: [
		{ id: 'settings.phone-open', checkpoint: 'settings-open', visual: 'The settings menu covers the right side of the phone above a dimmed chat, its close button where the settings button was.', devices: ['web-phone'] },
		{ id: 'settings.phone-closed', checkpoint: 'settings-closed', visual: 'The settings menu and the dim backdrop are gone and the settings button is back.', devices: ['web-phone'] },
		{ id: 'settings.narrow-open', checkpoint: 'settings-open', visual: 'The settings menu sits over a dimmed chat at the right edge of the window.', devices: ['web-laptop'] },
		{ id: 'settings.narrow-closed', checkpoint: 'settings-closed', visual: 'The settings menu and the dim backdrop are gone.', devices: ['web-laptop'] },
	],
	tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 3000 },
});

/**
 * Settings menu overlay motion (TASK-4266 follow-up): on screens where the settings menu is
 * an overlay it slides in from the right with the chat sidebar's ease-in-out and duration over
 * a dim backdrop, and its close button sits on the button that opened it.
 */

type Sample = { t: number; panelLeft: number; backdropOpacity: number; visibility: string };

/** Samples the panel position and backdrop opacity every frame until the motion has settled. */
async function sampleDuring(page: Page, action: () => Promise<void>, maxMs = 4000): Promise<Sample[]> {
	const pending = page.evaluate((capMs: number) => new Promise<Sample[]>((resolve) => {
		const panel = document.querySelector<HTMLElement>('[data-testid="settings-menu"]');
		const backdrop = document.querySelector<HTMLElement>('[data-testid="settings-chat-backdrop"]');
		if (!panel || !backdrop) throw new Error('Settings panel or backdrop is missing');
		const samples: Sample[] = [];
		const start = performance.now();
		let lastChange = start;
		let sawChange = false;
		const tick = (now: number) => {
			const sample = {
				t: now - start,
				panelLeft: panel.getBoundingClientRect().left,
				backdropOpacity: Number(getComputedStyle(backdrop).opacity),
				visibility: getComputedStyle(panel).visibility
			};
			const previous = samples[samples.length - 1];
			if (
				previous &&
				(previous.panelLeft !== sample.panelLeft ||
					previous.backdropOpacity !== sample.backdropOpacity ||
					previous.visibility !== sample.visibility)
			) {
				sawChange = true;
				lastChange = now;
			}
			samples.push(sample);
			if ((sawChange && now - lastChange >= 150) || now - start >= capMs) resolve(samples);
			else requestAnimationFrame(tick);
		};
		requestAnimationFrame(tick);
	}), maxMs);
	await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
	await action();
	return pending;
}

async function openGuestApp(page: Page, width: number, height: number): Promise<void> {
	await page.setViewportSize({ width, height });
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 30000 });
	await page.evaluate(() => document.fonts.ready);
	await page.waitForTimeout(500);
}

function center(box: { x: number; y: number; width: number; height: number }) {
	return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

async function checkOverlayMotion(page: Page, testInfo: TestInfo, device: 'web-phone' | 'web-laptop', width: number, height: number, tapX: number): Promise<void> {
	const proof = createVideoProofRuntime(settingsProof, { device, attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
	const label = device === 'web-phone' ? 'phone' : 'narrow';
	await openGuestApp(page, width, height);
	const opener = page.getByTestId('profile-container');
	const panel = page.getByTestId('settings-menu');
	const backdrop = page.getByTestId('settings-chat-backdrop');
	const closeButton = page.getByTestId('icon-button-close');
	await expect(panel).toBeHidden();
	await expect(backdrop).toBeHidden();
	const openerBox = (await opener.boundingBox())!;
	await testInfo.attach(`${label}-closed`, { body: await page.screenshot(), contentType: 'image/png' });

	const opening = await sampleDuring(page, () => opener.click());
	await expect(panel).toBeVisible();
	await expect(backdrop).toBeVisible();
	const finalLeft = opening[opening.length - 1].panelLeft;
	const startLeft = opening[0].panelLeft;
	// It slides from beyond the right edge: intermediate frames sit between the start and the final position.
	expect(startLeft).toBeGreaterThan(finalLeft + 100);
	const moving = opening.filter((s) => s.panelLeft < startLeft - 2 && s.panelLeft > finalLeft + 2);
	expect(moving.length).toBeGreaterThanOrEqual(3);
	// The backdrop fades in with it (intermediate opacities) and ends at full opacity.
	expect(opening.some((s) => s.backdropOpacity > 0.05 && s.backdropOpacity < 0.95)).toBe(true);
	expect(opening[opening.length - 1].backdropOpacity).toBe(1);
	// Same easing and duration as the chat sidebar, configured on the panel and the backdrop.
	for (const element of [panel, backdrop]) {
		const motion = await element.evaluate((el: HTMLElement) => {
			const style = getComputedStyle(el);
			return { duration: style.transitionDuration, easing: style.transitionTimingFunction };
		});
		expect(motion.easing).toContain('cubic-bezier(0.65, 0, 0.35, 1)');
		expect(motion.duration).toContain('0.3s');
	}
	// The backdrop is a real dim, not transparent.
	const dim = await backdrop.evaluate((el: HTMLElement) => getComputedStyle(el).backgroundColor);
	expect(dim).toMatch(/rgba\(0, 0, 0, 0\.45\)/);
	await page.waitForTimeout(100);
	await testInfo.attach(`${label}-open`, { body: await page.screenshot(), contentType: 'image/png' });

	// The close button sits exactly where the button that opened the menu was.
	const closeBox = (await closeButton.boundingBox())!;
	expect(Math.abs(center(closeBox).x - center(openerBox).x)).toBeLessThanOrEqual(1);
	expect(Math.abs(center(closeBox).y - center(openerBox).y)).toBeLessThanOrEqual(1);
	await proof.assert(`settings.${label}-open`, async () => {
		await expect(panel).toBeVisible();
		await expect(backdrop).toBeVisible();
	});
	await proof.checkpoint('settings-open');

	// Closing slides it back out the same way and keeps it visible while it leaves.
	const closing = await sampleDuring(page, () => closeButton.click());
	await expect(panel).toBeHidden();
	await expect(backdrop).toBeHidden();
	const slideOut = closing.filter((s) => s.panelLeft > finalLeft + 2 && s.panelLeft < startLeft - 2);
	expect(slideOut.length).toBeGreaterThanOrEqual(3);
	expect(slideOut.every((s) => s.visibility === 'visible')).toBe(true);
	expect(closing.some((s) => s.backdropOpacity > 0.05 && s.backdropOpacity < 0.95)).toBe(true);
	await proof.assert(`settings.${label}-closed`, async () => {
		await expect(panel).toBeHidden();
		await expect(backdrop).toBeHidden();
	});
	await proof.checkpoint('settings-closed');

	// Tapping the dim backdrop closes it too.
	await opener.click();
	await expect(backdrop).toBeVisible();
	// A locator click with a position fails with the intercepting element when something covers the backdrop.
	await backdrop.click({ position: { x: tapX, y: Math.round(height / 2) } });
	await expect(panel).toBeHidden();
	await expect(backdrop).toBeHidden();
	await proof.attach();
}

// contract-test: direct surface=gui.web assertions=settings-ui.overlay.eased-motion
test('phone: settings menu slides in from the right with the sidebar easing and a dim backdrop', async ({ page }: { page: Page }, testInfo: TestInfo) => {
	await checkOverlayMotion(page, testInfo, 'web-phone', 390, 844, 20);
});

// contract-test: direct surface=gui.web assertions=settings-ui.overlay.eased-motion
test('narrow desktop window: settings menu overlay uses the same motion', async ({ page }: { page: Page }, testInfo: TestInfo) => {
	await checkOverlayMotion(page, testInfo, 'web-laptop', 1000, 760, 40);
});

// contract-test: direct surface=gui.web assertions=settings-ui.overlay.eased-motion
test('phone: reduced motion opens and closes the settings menu without animation', async ({ page }: { page: Page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await openGuestApp(page, 390, 844);
	const panel = page.getByTestId('settings-menu');
	const opening = await sampleDuring(page, () => page.getByTestId('profile-container').click());
	await expect(panel).toBeVisible();
	const finalLeft = opening[opening.length - 1].panelLeft;
	const startLeft = opening[0].panelLeft;
	expect(opening.filter((s) => s.panelLeft < startLeft - 2 && s.panelLeft > finalLeft + 2).length).toBeLessThanOrEqual(1);
	await page.getByTestId('icon-button-close').click();
	await expect(panel).toBeHidden();
});
