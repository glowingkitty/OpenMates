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
const PRIVACY_DURATION_MS = HEADING_TRANSITION_MS + 20000;
const STORY_DURATION_MS = HEADING_TRANSITION_MS + 12000;
const ADVANCE_GRACE_MS = 4000;
const INTRO_TO_ACTIONABLE_MAX_MS = 700;

const PRIVACY_STAGES = [
	'saved-data-copy',
	'encryption-lock',
	'pii-copy',
	'pii-detection',
	'originals-copy',
	'pii-reveal',
	'personalized-copy',
	'trip-request',
	'memory-permission'
] as const;

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
	test('intro advances promptly and every heading uses the shared motion lifecycle', async ({ page }: { page: any }) => {
		test.setTimeout(30000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/?landing-header-motion'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-heading-motion')).toHaveAttribute('data-motion-phase', /entering|visible/);

		const transitionStartedAt = Date.now();
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.', {
			timeout: INTRO_TO_ACTIONABLE_MAX_MS
		});
		expect(Date.now() - transitionStartedAt).toBeLessThan(INTRO_TO_ACTIONABLE_MAX_MS);
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-motion-phase', /entering|visible/);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'ready', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('landing-subslide-motion')).toHaveAttribute('data-stage', 'user-request');
		await expect(page.getByTestId('landing-subslide-motion')).toHaveCSS('animation-name', /landingSubslideFlow$/);
	});

	test('stories use coordinated timelines and one compact heading structure', async ({ page }: { page: any }) => {
		test.setTimeout(100000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await openPrivacySlide(page);

		await expect(page.getByTestId('landing-privacy-safety-demo')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'false');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'ready', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[0]);
		await expect(page.getByTestId('landing-privacy-saved-data-copy')).toContainText('Only your devices can decrypt all your data.');
		let durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(PRIVACY_DURATION_MS);
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[1], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-lock')).toHaveAttribute('data-lock-state', 'locked', { timeout: 2500 });
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[2], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-copy')).toContainText('Personal details are replaced, before the AI sees them.');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[3], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-highlight')).toHaveCSS('background-color', 'rgba(250, 204, 21, 0.35)');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[4], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-originals-copy')).toContainText('Only you can view the originals.');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[5], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-reveal')).toHaveAttribute('data-pii-revealed', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[6], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-personalized-copy')).toContainText('Personalized responses. But only when you want them.');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[7], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-trip-request')).toContainText('Recommended places for my next trip?');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[8], { timeout: 4000 });
		await expect(page.getByTestId('app-settings-memories-permission-card')).toBeVisible();
		await expect(page.getByTestId('landing-memory-category-name')).toContainText(/Trips|Reisen/);

		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible({ timeout: PRIVACY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('No deep tech knowledge needed.');
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

	test('guest New chat from an example focuses a blank composer without replaying slide zero', async ({ page }: { page: any }) => {
		test.setTimeout(30000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/#chat-id=example-privacy-first-local-ai'), { waitUntil: 'domcontentloaded' });
		const newChatButton = page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
		await expect(newChatButton).toBeVisible({ timeout: 15000 });
		await newChatButton.click();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect(page.getByTestId('message-editor')).toBeFocused({ timeout: 5000 });
		await expect.poll(async () => page.evaluate(() => window.location.hash)).not.toContain('chat-id=');
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
