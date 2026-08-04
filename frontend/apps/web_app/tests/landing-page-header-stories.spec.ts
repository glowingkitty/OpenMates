/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Focused deployed coverage for the landing header product stories.
 * Keeps the privacy, mates/focus, people-first, and reduced-motion contracts
 * independent from legacy landing intro geometry assertions.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const HEADING_SETTLE_MS = 3000;
const HEADING_TRANSITION_MS = 1500 + 420 + 420;
const PRIVACY_DURATION_MS = HEADING_TRANSITION_MS + 15000;
const STORY_DURATION_MS = HEADING_TRANSITION_MS + 12000;
const ADVANCE_GRACE_MS = 4000;

async function openPrivacySlide(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/?landing-header-stories'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Privacy & safety by design.');
}

test.describe('Landing page header stories', () => {
	test('stories use coordinated timelines and one compact heading structure', async ({ page }: { page: any }) => {
		test.setTimeout(70000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await openPrivacySlide(page);

		await expect(page.getByTestId('landing-privacy-safety-demo')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'false');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'ready', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', 'encryption');
		await expect(page.getByTestId('landing-privacy-encryption')).toContainText('Only your devices can unlock your saved data.');
		let durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(PRIVACY_DURATION_MS);
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', 'pii', { timeout: 6500 });
		await expect(page.getByTestId('landing-privacy-pii-original')).toContainText('alex@example.com');
		await expect(page.getByTestId('landing-privacy-pii-placeholder')).toContainText('[EMAIL_com]');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', 'memory', { timeout: 6500 });
		await expect(page.getByTestId('landing-privacy-memory-consent')).toBeVisible();

		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible({ timeout: PRIVACY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Without needing deep technical know-how.');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'ready', { timeout: HEADING_SETTLE_MS });
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'mates');
		await expect(page.getByTestId('landing-mate-profile')).toHaveCount(4);
		durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(STORY_DURATION_MS);
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'focus', { timeout: 7500 });
		await expect(page.getByTestId('landing-focus-mode')).toHaveCount(3);

		await expect(page.getByTestId('landing-people-experience-demo')).toBeVisible({ timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Built for people & the best possible experience.');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'ready', { timeout: HEADING_SETTLE_MS });
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'providers');
		await expect(page.getByTestId('landing-provider-logo')).toHaveCount(4);
		durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(STORY_DURATION_MS);
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'access', { timeout: 7500 });
		await expect(page.getByTestId('landing-platform-label')).toHaveText(['Web', 'CLI', 'SDK']);

		await expect(page.getByTestId('landing-signup-cta')).toBeVisible({ timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-next')).toHaveCount(0);
	});

	test('reduced motion is static and manually navigable', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await page.setViewportSize({ width: 1280, height: 800 });
		await openPrivacySlide(page);

		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-reduced-motion', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'false');
		await expect(page.getByTestId('landing-privacy-summary')).toBeVisible();
		await expect(page.getByTestId('daily-inspiration-carousel-progress-fill')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
		await page.waitForTimeout(16000);
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Privacy & safety by design.');
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible();
	});
});
