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

const LANDING_INTRO_VIEWPORTS = [
	{ name: 'iphone', width: 390, height: 844, minAiIconWidth: 54, maxHeadlineRequestGap: 42 },
	{ name: 'ipad-portrait', width: 768, height: 1024, minAiIconWidth: 64, maxHeadlineRequestGap: 54 },
	{ name: 'ipad-landscape', width: 1024, height: 768, minAiIconWidth: 58, maxHeadlineRequestGap: 46 },
	{ name: 'macbook-landscape', width: 1280, height: 800, minAiIconWidth: 58, maxHeadlineRequestGap: 46 },
	{ name: 'full-hd', width: 1920, height: 1080, minAiIconWidth: 74, maxHeadlineRequestGap: 64 }
];

async function skipExpandedLandingIntro(page: any): Promise<void> {
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
}

async function waitForLandingIntroExamples(page: any): Promise<void> {
	await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
	await expect.poll(async () => page.getByTestId('landing-intro-request').textContent(), { timeout: 6000 }).toBeTruthy();
}

async function landingIntroLayoutMetrics(page: any): Promise<{
	activeSideGap: number;
	activeBottomGap: number;
	aiIconWidth: number;
	headlineTextAlign: string;
	headlineCenterDelta: number;
	headlineSpanCenterDeltas: number[];
	headlineSpanRectCounts: number[];
	headlineRequestGap: number;
	railRowCount: number;
	railRows: Array<{
		rowTopVisible: boolean;
		rowBottomVisible: boolean;
		visibleIconCount: number;
		bottomGap: number;
	}>;
}> {
	return page.evaluate(() => {
		const active = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const aiIcon = document.querySelector<HTMLElement>('[data-testid="guest-intro-ai-icon"]');
		const headline = document.querySelector<HTMLElement>('[data-testid="landing-intro-headline"]');
		const request = document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]');
		const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'))
			.map((rail) => rail.parentElement as HTMLElement | null)
			.filter((row): row is HTMLElement => Boolean(row));
		if (!active || !banner || !aiIcon || !headline || !request || rows.length !== 2) {
			throw new Error('Landing intro layout elements missing');
		}

		const activeRect = active.getBoundingClientRect();
		const bannerRect = banner.getBoundingClientRect();
		const aiIconRect = aiIcon.getBoundingClientRect();
		const headlineRect = headline.getBoundingClientRect();
		const requestRect = request.getBoundingClientRect();
		const headlineCenter = headlineRect.left + headlineRect.width / 2;
		const bannerCenter = bannerRect.left + bannerRect.width / 2;
		const headlineSpans = Array.from(headline.querySelectorAll<HTMLElement>('span'));

		return {
			activeSideGap: Math.min(activeRect.left, window.innerWidth - activeRect.right),
			activeBottomGap: window.innerHeight - activeRect.bottom,
			aiIconWidth: aiIconRect.width,
			headlineTextAlign: getComputedStyle(headline).textAlign,
			headlineCenterDelta: Math.abs(headlineCenter - bannerCenter),
			headlineSpanCenterDeltas: headlineSpans.map((span) => {
				const rect = span.getBoundingClientRect();
				return Math.abs((rect.left + rect.width / 2) - headlineCenter);
			}),
			headlineSpanRectCounts: headlineSpans.map((span) => span.getClientRects().length),
			headlineRequestGap: requestRect.top - headlineRect.bottom,
			railRowCount: rows.length,
			railRows: rows.map((row) => {
				const rowRect = row.getBoundingClientRect();
				const icons = Array.from(row.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"]'));
				const visibleIconCount = icons.filter((icon) => {
					const iconRect = icon.getBoundingClientRect();
					return iconRect.right > bannerRect.left && iconRect.left < bannerRect.right && iconRect.bottom > bannerRect.top && iconRect.top < bannerRect.bottom;
				}).length;
				return {
					rowTopVisible: rowRect.top >= bannerRect.top - 1,
					rowBottomVisible: rowRect.bottom <= bannerRect.bottom + 1,
					visibleIconCount,
					bottomGap: bannerRect.bottom - rowRect.bottom
				};
			})
		};
	});
}

test.describe('Landing page onboarding refresh', () => {
	test('expanded intro fits all target device viewports', async ({ page }: { page: any }) => {
		test.setTimeout(120000);

		for (const viewport of LANDING_INTRO_VIEWPORTS) {
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			await page.goto(getE2EDebugUrl(`/?landing-layout=${viewport.name}`), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');
			await waitForLandingIntroExamples(page);

			const metrics = await landingIntroLayoutMetrics(page);
			expect(metrics.activeBottomGap, `${viewport.name}: bottom gap should match side gap`).toBeLessThanOrEqual(metrics.activeSideGap + 3);
			expect(metrics.activeBottomGap, `${viewport.name}: bottom gap should not collapse`).toBeGreaterThanOrEqual(Math.max(0, metrics.activeSideGap - 3));
			expect(metrics.aiIconWidth, `${viewport.name}: AI icon is too small`).toBeGreaterThanOrEqual(viewport.minAiIconWidth);
			expect(metrics.headlineTextAlign, `${viewport.name}: headline should be center aligned`).toBe('center');
			expect(metrics.headlineCenterDelta, `${viewport.name}: headline should be centered in banner`).toBeLessThanOrEqual(3);
			expect(metrics.headlineSpanCenterDeltas, `${viewport.name}: headline line count`).toHaveLength(2);
			for (const delta of metrics.headlineSpanCenterDeltas) {
				expect(delta, `${viewport.name}: headline line center mismatch`).toBeLessThanOrEqual(3);
			}
			expect(metrics.headlineSpanRectCounts, `${viewport.name}: headline should stay two visual lines`).toEqual([1, 1]);
			expect(metrics.headlineRequestGap, `${viewport.name}: heading/message gap should be positive`).toBeGreaterThanOrEqual(4);
			expect(metrics.headlineRequestGap, `${viewport.name}: heading/message gap too large`).toBeLessThanOrEqual(viewport.maxHeadlineRequestGap);
			expect(metrics.railRowCount, `${viewport.name}: app rail row count`).toBe(2);
			for (const row of metrics.railRows) {
				expect(row.rowTopVisible, `${viewport.name}: app row top clipped`).toBe(true);
				expect(row.rowBottomVisible, `${viewport.name}: app row bottom clipped`).toBe(true);
				expect(row.visibleIconCount, `${viewport.name}: app row needs visible icons`).toBeGreaterThanOrEqual(5);
				expect(row.bottomGap, `${viewport.name}: app row is below the banner`).toBeGreaterThanOrEqual(0);
			}
		}
	});

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
				bannerLayoutHeight: banner.offsetHeight,
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

		expect(metrics.bannerLayoutHeight).toBeGreaterThanOrEqual(240);
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
