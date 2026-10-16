/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// Retains the viewport and reduced-motion coverage that applies to the ordinary banner.
test.describe('Signed-out welcome header', () => {
	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,daily-inspiration.guest-isolated
	test('normal banner and composer fit phone and laptop viewports', async ({ page }: { page: any }) => {
		for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
			await page.setViewportSize(viewport);
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			const banner = page.getByTestId('daily-inspiration-banner');
			await expect(banner).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('message-editor')).toBeVisible();
			await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
			const bounds = await banner.boundingBox();
			expect(bounds).not.toBeNull();
			expect(bounds!.x).toBeGreaterThanOrEqual(0);
			expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
		}
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,daily-inspiration.guest-isolated
	test('reduced motion leaves ordinary inspirations readable', async ({ page }: { page: any }) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
	});
});
