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
	test('actionable slide shows the Luma event preview cursor-to-CTA animation', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Not just a wall of text.', { timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-assistant-profile')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-user-message')).toContainText(
			'Find tech events in Berlin'
		);
		await expect(page.getByTestId('landing-actionable-assistant-message')).toContainText(
			'I found a real Luma event'
		);
		await expect(page.getByTestId('landing-actionable-event-preview')).toContainText('DEPIN DAY BERLIN');
		await expect(page.getByTestId('landing-actionable-event-preview').getByTestId('embed-preview')).toHaveAttribute(
			'data-app-id',
			'events'
		);
		await expect(page.getByTestId('landing-actionable-event-cta-card')).toContainText('Luma event');
		await expect(page.getByTestId('landing-actionable-luma-button')).toContainText('Open on Luma');
		await expect(page.getByTestId('landing-actionable-cursor')).toBeVisible();
		await expect(page.getByTestId('landing-actionable-event-fullscreen')).toHaveCount(0);
		await expect(page.getByTestId('landing-actionable-event-map')).toHaveCount(0);
		await expect(page.getByTestId('guest-intro-video-shell')).toHaveCount(0);

		const metrics = await page.evaluate(() => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const headline = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-phrase"]');
			const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
			const scene = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-scene"]');
			const userMessage = document.querySelector<HTMLElement>('[data-testid="landing-actionable-user-message"]');
			const assistantMessage = document.querySelector<HTMLElement>('[data-testid="landing-actionable-assistant-message"]');
			const assistantProfile = document.querySelector<HTMLElement>('[data-testid="landing-actionable-assistant-profile"]');
			const previewEmbed = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-preview"] [data-testid="embed-preview"]');
			const ctaCard = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-cta-card"]');
			const ctaButton = document.querySelector<HTMLElement>('[data-testid="landing-actionable-luma-button"]');
			const cursor = document.querySelector<HTMLElement>('[data-testid="landing-actionable-cursor"]');
			const previewImage = document.querySelector<HTMLImageElement>('[data-testid="landing-actionable-event-preview"] img');
			if (!banner || !headline || !demo || !scene || !userMessage || !assistantMessage || !assistantProfile || !previewEmbed || !ctaCard || !ctaButton || !cursor || !previewImage) {
				throw new Error('Actionable slide elements missing');
			}

			const bannerRect = banner.getBoundingClientRect();
			const headlineRect = headline.getBoundingClientRect();
			const demoRect = demo.getBoundingClientRect();
			const userTail = getComputedStyle(userMessage, '::before');
			const assistantTail = getComputedStyle(assistantMessage, '::before');
			const assistantProfileStyle = getComputedStyle(assistantProfile);
			const ctaCardStyle = getComputedStyle(ctaCard);
			const cursorStyle = getComputedStyle(cursor);
			return {
				bannerHeight: bannerRect.height,
				demoWidth: demoRect.width,
				demoHeight: demoRect.height,
				demoLeftGap: demoRect.left - bannerRect.left,
				demoRightGap: bannerRect.right - demoRect.right,
				headlineDemoGap: demoRect.left - headlineRect.right,
				sceneAnimation: getComputedStyle(scene).animationName,
				userTailWidth: Number.parseFloat(userTail.width),
				userTailHeight: Number.parseFloat(userTail.height),
				assistantTailWidth: Number.parseFloat(assistantTail.width),
				assistantTailHeight: Number.parseFloat(assistantTail.height),
				assistantProfileBackground: assistantProfileStyle.backgroundImage,
				previewStatus: previewEmbed.dataset.status,
				previewSkillId: previewEmbed.dataset.skillId,
				previewImageSrc: previewImage.currentSrc || previewImage.src,
				previewProvider: previewEmbed.textContent || '',
				ctaCardAnimation: ctaCardStyle.animationName,
				ctaButtonText: ctaButton.textContent?.trim() || '',
				cursorAnimation: cursorStyle.animationName
			};
		});

		expect(metrics.bannerHeight).toBeGreaterThanOrEqual(240);
		expect(metrics.demoWidth).toBeGreaterThanOrEqual(360);
		expect(metrics.demoHeight).toBeLessThanOrEqual(metrics.bannerHeight);
		expect(metrics.demoLeftGap).toBeGreaterThanOrEqual(40);
		expect(metrics.demoRightGap).toBeGreaterThanOrEqual(40);
		expect(metrics.headlineDemoGap).toBeGreaterThanOrEqual(24);
		expect(metrics.sceneAnimation).toContain('landingActionableScene');
		expect(metrics.userTailWidth).toBeGreaterThanOrEqual(10);
		expect(metrics.userTailHeight).toBeGreaterThanOrEqual(18);
		expect(metrics.assistantTailWidth).toBeGreaterThanOrEqual(10);
		expect(metrics.assistantTailHeight).toBeGreaterThanOrEqual(18);
		expect(metrics.assistantProfileBackground).toContain('general_knowledge');
		expect(metrics.previewStatus).toBe('finished');
		expect(metrics.previewSkillId).toBe('event');
		expect(metrics.previewImageSrc).toContain('lumacdn.com');
		expect(metrics.previewProvider).toContain('Luma');
		expect(metrics.ctaCardAnimation).toContain('landingActionableCtaCard');
		expect(metrics.ctaButtonText).toBe('Open on Luma');
		expect(metrics.cursorAnimation).toContain('landingActionableCursor');
	});
});
