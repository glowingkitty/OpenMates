/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Landing page onboarding refresh E2E coverage.
 *
 * Verifies the logged-out landing product explainer contract from
 * docs/specs/landing-page-onboarding-refresh/spec.yml after the expanded first
 * intro collapses into regular daily inspiration slides.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

async function skipExpandedLandingIntro(page: any): Promise<void> {
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
}

test.describe('Landing page onboarding refresh', () => {
	test('actionable slide shows the language-learning event explainer animation', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Not just a wall of text.', { timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-user-message')).toContainText(
			'Find language-learning events in Berlin'
		);
		await expect(page.getByTestId('landing-actionable-assistant-message')).toContainText(
			'Sure, let me help with that!'
		);
		await expect(page.getByTestId('landing-actionable-event-preview')).toContainText('Berlin Language Exchange');
		await expect(page.getByTestId('landing-actionable-event-fullscreen')).toContainText(
			'Practice German and English'
		);
		await expect(page.getByTestId('guest-intro-video-shell')).toHaveCount(0);

		const metrics = await page.evaluate(() => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const headline = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-phrase"]');
			const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
			const scene = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-scene"]');
			if (!banner || !headline || !demo || !scene) throw new Error('Actionable slide elements missing');

			const bannerRect = banner.getBoundingClientRect();
			const headlineRect = headline.getBoundingClientRect();
			const demoRect = demo.getBoundingClientRect();
			return {
				bannerHeight: bannerRect.height,
				demoWidth: demoRect.width,
				demoHeight: demoRect.height,
				demoLeftGap: demoRect.left - bannerRect.left,
				demoRightGap: bannerRect.right - demoRect.right,
				headlineDemoGap: demoRect.left - headlineRect.right,
				sceneAnimation: getComputedStyle(scene).animationName
			};
		});

		expect(metrics.bannerHeight).toBeGreaterThanOrEqual(240);
		expect(metrics.demoWidth).toBeGreaterThanOrEqual(360);
		expect(metrics.demoHeight).toBeLessThanOrEqual(metrics.bannerHeight);
		expect(metrics.demoLeftGap).toBeGreaterThanOrEqual(40);
		expect(metrics.demoRightGap).toBeGreaterThanOrEqual(40);
		expect(metrics.headlineDemoGap).toBeGreaterThanOrEqual(24);
		expect(metrics.sceneAnimation).toContain('landingActionableScene');
	});
});
