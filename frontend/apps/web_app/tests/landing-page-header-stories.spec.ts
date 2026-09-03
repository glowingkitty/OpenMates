/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Focused deployed coverage for the landing header product stories.
 * Keeps the privacy, mates/focus, people-first, and reduced-motion contracts
 * independent from legacy landing intro geometry assertions.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const HEADING_SETTLE_MS = 4000;
const HEADING_TRANSITION_MS = 2100 + 420 + 120;
const PRIVACY_DURATION_MS = HEADING_TRANSITION_MS + 20000;
const STORY_DURATION_MS = HEADING_TRANSITION_MS + 12000;
const ADVANCE_GRACE_MS = 4000;
const INTRO_TO_ACTIONABLE_MAX_MS = 700;
const MOBILE_MINI_HEADING_MAX_BOTTOM_OVERFLOW_PX = 1;
const MOBILE_TEXT_CONTRAST_MIN = 3;

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

const PRIVACY_STAGE_TEST_IDS = {
	'saved-data-copy': 'landing-privacy-saved-data-copy',
	'encryption-lock': 'landing-privacy-encryption',
	'pii-copy': 'landing-privacy-pii-copy',
	'pii-detection': 'landing-privacy-pii-message',
	'originals-copy': 'landing-privacy-originals-copy',
	'pii-reveal': 'landing-privacy-pii-reveal',
	'personalized-copy': 'landing-privacy-personalized-copy',
	'trip-request': 'landing-privacy-trip-request',
	'memory-permission': 'app-settings-memories-permission-card'
} as const;

async function openPrivacySlide(page: any, reducedMotion = false): Promise<void> {
	await page.goto(getE2EDebugUrl('/?landing-header-stories'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
	await expect(page.getByTestId(reducedMotion ? 'landing-privacy-summary' : 'daily-inspiration-phrase')).toBeVisible();
	await expect(page.getByTestId('guest-feature-inline-icon')).toHaveCount(0);
	await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveCount(reducedMotion ? 1 : 0);
}

async function expectInsideBanner(page: any, testId: string): Promise<void> {
	const banner = await page.getByTestId('daily-inspiration-banner').boundingBox();
	const content = await page.getByTestId(testId).boundingBox();
	expect(banner).not.toBeNull();
	expect(content).not.toBeNull();
	expect(content!.x).toBeGreaterThanOrEqual(banner!.x - 4);
	expect(content!.y).toBeGreaterThanOrEqual(banner!.y - 4);
	expect(content!.x + content!.width).toBeLessThanOrEqual(banner!.x + banner!.width + 4);
	expect(content!.y + content!.height).toBeLessThanOrEqual(banner!.y + banner!.height + 4);
}

test.describe('Landing page header stories', () => {
	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.coordinated-story-progress,landing-onboarding.manual-navigation
	test('intro advances promptly and every heading uses the shared motion lifecycle', async ({ page }: { page: any }) => {
		test.setTimeout(30000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/?landing-header-motion'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-heading-motion')).toHaveAttribute('data-motion-phase', /entering|visible/);
		await expect(page.getByTestId('landing-intro-heading-motion')).toHaveAttribute('data-enter-direction', 'from-below');
		await expect(page.getByTestId('landing-intro-heading-motion')).toHaveAttribute('data-exit-direction', 'to-above');
		const desktopIntroGap = await page.evaluate(() => {
			const heading = document.querySelector('[data-testid="landing-intro-headline"]')?.getBoundingClientRect();
			const request = document.querySelector('[data-testid="landing-intro-request"]')?.getBoundingClientRect();
			return heading && request ? request.top - heading.bottom : Number.POSITIVE_INFINITY;
		});
		expect(desktopIntroGap).toBeLessThanOrEqual(96);

		const transitionStartedAt = Date.now();
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.', {
			timeout: INTRO_TO_ACTIONABLE_MAX_MS
		});
		expect(Date.now() - transitionStartedAt).toBeLessThan(INTRO_TO_ACTIONABLE_MAX_MS);
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-motion-phase', /entering|visible/);
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-enter-direction', 'from-below');
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-exit-direction', 'to-above');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.');
		await expect(page.getByTestId('guest-feature-inline-icon')).toHaveCount(0);
		await expect(page.getByTestId('landing-subslide-motion')).toHaveAttribute('data-stage', 'user-request');
		await expect(page.getByTestId('landing-subslide-motion')).toHaveCSS('animation-name', /landingSubslideFlow$/);
		await expectInsideBanner(page, 'landing-actionable-event-demo');
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories,landing-onboarding.signup-cta
	test('stories use coordinated heading-only and animation-only timelines', async ({ page }: { page: any }) => {
		test.setTimeout(100000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await openPrivacySlide(page);

		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-motion-phase', 'hidden');
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Privacy & safety by design.');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toBeVisible();
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[0]);
		await expect(page.getByTestId('landing-privacy-saved-data-copy')).toContainText('Only your devices can decrypt all your data.');
		await expectInsideBanner(page, 'landing-privacy-saved-data-copy');
		let durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(PRIVACY_DURATION_MS);
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[1], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-lock')).toHaveAttribute('data-lock-state', 'locked', { timeout: 2500 });
		await expectInsideBanner(page, 'landing-privacy-encryption');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[2], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-copy')).toContainText('Personal details are replaced, before the AI sees them.');
		await expectInsideBanner(page, 'landing-privacy-pii-copy');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[3], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-message')).toContainText('Prepare an email to alex@example.com');
		await expect(page.getByTestId('landing-privacy-pii-message')).toHaveAttribute('data-pii-state', 'plain');
		await expect(page.getByTestId('landing-privacy-pii-message')).toHaveAttribute('data-pii-state', 'highlighted', { timeout: 1200 });
		await expect(page.getByTestId('landing-privacy-pii-highlight')).toHaveCSS('background-color', 'rgba(250, 204, 21, 0.35)');
		await expect(page.getByTestId('landing-privacy-pii-message')).toHaveAttribute('data-pii-state', 'placeholder', { timeout: 1200 });
		await expect(page.getByTestId('landing-privacy-pii-placeholder')).toHaveText('[EMAIL_1]');
		await expectInsideBanner(page, 'landing-privacy-pii-message');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[4], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-originals-copy')).toContainText('Only you can view the originals.');
		await expectInsideBanner(page, 'landing-privacy-originals-copy');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[5], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-pii-reveal')).toHaveAttribute('data-pii-state', 'placeholder');
		await expect(page.getByTestId('landing-privacy-assistant-name')).toHaveText(/Burton/);
		await expect(page.getByTestId('landing-privacy-assistant-profile')).toHaveAttribute('data-mate-id', 'business_development');
		await expect(page.getByTestId('landing-privacy-assistant-message')).toContainText('Ok, preparing an email to [EMAIL_1]');
		await expect(page.getByTestId('landing-privacy-pii-reveal')).toHaveAttribute('data-pii-state', 'original', { timeout: 1600 });
		await expect(page.getByTestId('landing-privacy-assistant-message')).toContainText('Ok, preparing an email to alex@example.com');
		await expectInsideBanner(page, 'landing-privacy-pii-reveal');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[6], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-personalized-copy')).toContainText('Personalized responses. But only when you want them.');
		await expectInsideBanner(page, 'landing-privacy-personalized-copy');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[7], { timeout: 4000 });
		await expect(page.getByTestId('landing-privacy-trip-request')).toContainText('Recommended places for my next trip?');
		expect(await page.getByTestId('landing-privacy-trip-request').evaluate((message: HTMLElement) => message.querySelector('svg') === null)).toBe(true);
		await expectInsideBanner(page, 'landing-privacy-trip-request');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', PRIVACY_STAGES[8], { timeout: 4000 });
		await expect(page.getByTestId('app-settings-memories-permission-card')).toBeVisible();
		await expect(page.getByTestId('landing-memory-category-name')).toContainText(/Trips|Reisen/);
		await expectInsideBanner(page, 'app-settings-memories-permission-card');

		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-mates-focus', { timeout: PRIVACY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('No deep tech knowledge needed.');
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveCount(0);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', { timeout: HEADING_SETTLE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('No deep tech knowledge needed.');
		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible();
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'mates-copy');
		await expect(page.getByTestId('landing-mates-copy')).toContainText('Your AI experts, specialized for different topics.');
		await expect(page.getByTestId('landing-mate-profile')).toHaveCount(0);
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'mates', { timeout: 3000 });
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'mates');
		await expect(page.getByTestId('landing-mate-profile')).toHaveCount(4);
		await expectInsideBanner(page, 'landing-mates-focus-demo');
		durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(STORY_DURATION_MS);
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'focus', { timeout: 7500 });
		await expect(page.getByTestId('landing-focus-mode')).toHaveCount(3);

		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-provider-cross-platform', { timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Build for the best possible user experience.');
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveCount(0);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', { timeout: HEADING_SETTLE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Build for the best possible user experience.');
		await expect(page.getByTestId('landing-people-experience-demo')).toBeVisible();
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'providers-copy');
		await expect(page.getByTestId('landing-providers-copy')).toContainText('All the best AI models, in one place.');
		await expect(page.getByTestId('landing-provider-logo')).toHaveCount(0);
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'providers', { timeout: 3000 });
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'providers');
		await expect(page.getByTestId('landing-provider-logo')).toHaveCount(4);
		await expectInsideBanner(page, 'landing-people-experience-demo');
		durationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(durationMs).toBe(STORY_DURATION_MS);
		await expect(page.getByTestId('landing-people-experience-demo')).toHaveAttribute('data-active-stage', 'access', { timeout: 7500 });
		await expect(page.getByTestId('landing-platform-label')).toHaveText('Web');
		await expect(page.getByTestId('landing-platform-url')).toHaveText('OpenMates.org');
		await expect(page.getByTestId('landing-platform-label')).toHaveText('CLI', { timeout: 3500 });
		await expect(page.getByTestId('landing-platform-command')).toContainText('npm install -g openmates');
		await expect(page.getByTestId('landing-platform-label')).toHaveText('SDK', { timeout: 3000 });
		await expect(page.getByTestId('landing-platform-sdk')).toContainText('from openmates import OpenMates');

		await expect(page.getByTestId('landing-signup-cta')).toBeVisible({ timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('daily-inspiration-next')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories
	test('mobile stories preserve spacing, readable copy, complete headings, and contained permission UI', async ({ page }: { page: any }) => {
		test.setTimeout(100000);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.addInitScript(() => {
			localStorage.setItem('theme_mode', 'dark');
			localStorage.setItem('theme', 'dark');
		});
		await page.goto(getE2EDebugUrl('/?landing-header-mobile-layout'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark');
		await expect(page.getByTestId('landing-intro-request')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('.landing-intro-headline-mobile')).toHaveText('Your AI team\nfor getting things done');
		await expect(page.locator('.landing-intro-headline-desktop')).toBeHidden();

		const introGap = await page.evaluate(() => {
			const heading = document.querySelector('[data-testid="landing-intro-headline"]')?.getBoundingClientRect();
			const request = document.querySelector('[data-testid="landing-intro-request"]')?.getBoundingClientRect();
			return heading && request ? request.top - heading.bottom : Number.POSITIVE_INFINITY;
		});
		expect(introGap).toBeLessThanOrEqual(96);

		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable');
		await expect(page.getByTestId('guest-feature-inline-icon')).toHaveCount(0);
		const actionableHeadingFontSize = await page.getByTestId('daily-inspiration-phrase').evaluate((heading: HTMLElement) => Number.parseFloat(getComputedStyle(heading).fontSize));
		expect(actionableHeadingFontSize).toBeGreaterThanOrEqual(32);
		const actionableHeadingBounds = await page.evaluate(() => {
			const banner = document.querySelector('[data-testid="daily-inspiration-banner"]')?.getBoundingClientRect();
			const heading = document.querySelector('[data-testid="daily-inspiration-phrase"]')?.getBoundingClientRect();
			return banner && heading ? {
				leftGap: heading.left - banner.left,
				rightGap: banner.right - heading.right,
				bottomOverflow: Math.max(0, heading.bottom - banner.bottom)
			} : null;
		});
		expect(actionableHeadingBounds).not.toBeNull();
		expect(actionableHeadingBounds!.leftGap, 'mobile headline should use the banner width while leaving arrow space').toBeLessThanOrEqual(52);
		expect(actionableHeadingBounds!.rightGap, 'mobile headline should use the banner width while leaving arrow space').toBeLessThanOrEqual(52);
		expect(actionableHeadingBounds!.bottomOverflow, 'mobile headline must not be clipped by the banner').toBeLessThanOrEqual(MOBILE_MINI_HEADING_MAX_BOTTOM_OVERFLOW_PX);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable');
		const actionableMiniHeading = await page.getByTestId('daily-inspiration-phrase').evaluate((heading: HTMLElement) => {
			const banner = document.querySelector('[data-testid="daily-inspiration-banner"]')?.getBoundingClientRect();
			const rect = heading.getBoundingClientRect();
			const style = getComputedStyle(heading);
			return {
				opacity: Number.parseFloat(style.opacity),
				fontSize: Number.parseFloat(style.fontSize),
				topGap: banner ? rect.top - banner.top : Number.POSITIVE_INFINITY,
				bottomOverflow: banner ? Math.max(0, rect.bottom - banner.bottom) : Number.POSITIVE_INFINITY
			};
		});
		expect(actionableMiniHeading.opacity, 'demo phase keeps a reduced-opacity mini heading').toBeGreaterThanOrEqual(0.35);
		expect(actionableMiniHeading.opacity, 'demo phase mini heading must remain visually secondary').toBeLessThanOrEqual(0.65);
		expect(actionableMiniHeading.fontSize, 'demo phase heading should shrink to a mini header').toBeLessThan(20);
		expect(actionableMiniHeading.topGap, 'mini heading should sit at the top of the banner').toBeLessThanOrEqual(18);
		expect(actionableMiniHeading.bottomOverflow, 'mini heading should not be clipped').toBeLessThanOrEqual(MOBILE_MINI_HEADING_MAX_BOTTOM_OVERFLOW_PX);
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible();

		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('landing-privacy-saved-data-copy')).toBeVisible({ timeout: 8000 });
		const savedDataCopy = page.getByTestId('landing-privacy-saved-data-copy');
		expect(await savedDataCopy.evaluate((stage: HTMLElement) => stage.querySelector('svg') === null)).toBe(true);
		expect(await savedDataCopy.evaluate((stage: HTMLElement) => Number.parseFloat(getComputedStyle(stage.querySelector('p')!).fontSize))).toBeGreaterThanOrEqual(20);
		await expectInsideBanner(page, 'landing-privacy-saved-data-copy');

		await expect(page.getByTestId('landing-privacy-pii-copy')).toBeVisible({ timeout: 8000 });
		const piiCopy = page.getByTestId('landing-privacy-pii-copy');
		expect(await piiCopy.evaluate((stage: HTMLElement) => stage.querySelector('svg') === null)).toBe(true);
		expect(await piiCopy.evaluate((stage: HTMLElement) => Number.parseFloat(getComputedStyle(stage.querySelector('p')!).fontSize))).toBeGreaterThanOrEqual(20);
		await expectInsideBanner(page, 'landing-privacy-pii-copy');

		await expect(page.getByTestId('landing-privacy-originals-copy')).toBeVisible({ timeout: 8000 });
		const originalsCopy = page.getByTestId('landing-privacy-originals-copy');
		expect(await originalsCopy.evaluate((stage: HTMLElement) => stage.querySelector('svg') === null)).toBe(true);
		expect(await originalsCopy.evaluate((stage: HTMLElement) => Number.parseFloat(getComputedStyle(stage.querySelector('p')!).fontSize))).toBeGreaterThanOrEqual(20);
		await expectInsideBanner(page, 'landing-privacy-originals-copy');

		await expect(page.getByTestId('landing-privacy-personalized-copy')).toBeVisible({ timeout: 8000 });
		const personalizedCopy = page.getByTestId('landing-privacy-personalized-copy');
		expect(await personalizedCopy.evaluate((stage: HTMLElement) => stage.querySelector('svg') === null)).toBe(true);
		expect(await personalizedCopy.evaluate((stage: HTMLElement) => Number.parseFloat(getComputedStyle(stage.querySelector('p')!).fontSize))).toBeGreaterThanOrEqual(20);
		await expectInsideBanner(page, 'landing-privacy-personalized-copy');

		await expect(page.getByTestId('app-settings-memories-permission-card')).toBeVisible({ timeout: 20000 });
		const permissionContained = await page.evaluate(() => {
			const demo = document.querySelector('[data-testid="landing-privacy-safety-demo"]')?.getBoundingClientRect();
			const card = document.querySelector('[data-testid="app-settings-memories-permission-card"]')?.getBoundingClientRect();
			return Boolean(demo && card
				&& card.left >= demo.left - 1
				&& card.right <= demo.right + 1
				&& card.top >= demo.top - 1
				&& card.bottom <= demo.bottom + 1);
		});
		expect(permissionContained).toBe(true);
		await expectInsideBanner(page, 'app-settings-memories-permission-card');

		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-mates-focus', { timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', { timeout: HEADING_SETTLE_MS });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('No deep tech knowledge needed.');
		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'mates', { timeout: 3000 });
		const mateRowMetrics = await page.evaluate(() => {
			function channel(value: number): number {
				const normalized = value / 255;
				return normalized <= 0.03928 ? normalized / 12.92 : Math.pow((normalized + 0.055) / 1.055, 2.4);
			}

			function parseRgb(value: string): [number, number, number] {
				const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
				return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : [0, 0, 0];
			}

			function luminance(value: string): number {
				const [r, g, b] = parseRgb(value).map(channel);
				return 0.2126 * r + 0.7152 * g + 0.0722 * b;
			}

			function contrast(foreground: string, background: string): number {
				const light = Math.max(luminance(foreground), luminance(background));
				const dark = Math.min(luminance(foreground), luminance(background));
				return (light + 0.05) / (dark + 0.05);
			}

			const demo = document.querySelector('[data-testid="landing-mates-focus-demo"]')?.getBoundingClientRect();
			const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="landing-mate-profile"]')];
			const active = rows.find((row) => row.classList.contains('active')) ?? rows[0];
			const rect = active?.getBoundingClientRect();
			const name = active?.querySelector<HTMLElement>('.mate-text-demo strong');
			const category = active?.querySelector<HTMLElement>('.mate-text-demo small');
			const nameRect = name?.getBoundingClientRect();
			const categoryRect = category?.getBoundingClientRect();
			const nameStyle = name ? getComputedStyle(name) : null;
			const categoryStyle = category ? getComputedStyle(category) : null;
			return demo && rect && nameRect && categoryRect && nameStyle && categoryStyle ? {
				contained: rect.left >= demo.left - 1 && rect.right <= demo.right + 1 && rect.top >= demo.top - 1 && rect.bottom <= demo.bottom + 1,
				categoryDisplay: categoryStyle.display,
				nameFitsRow: nameRect.left >= rect.left && nameRect.right <= rect.right && name.clientWidth > 0 && name.scrollWidth <= name.clientWidth,
				categoryFitsRow: categoryRect.left >= rect.left && categoryRect.right <= rect.right && category.clientWidth > 0 && category.scrollWidth <= category.clientWidth,
				nameContrast: contrast(nameStyle.color, getComputedStyle(active).backgroundColor),
				categoryContrast: contrast(categoryStyle.color, getComputedStyle(active).backgroundColor)
			} : null;
		});
		expect(mateRowMetrics).not.toBeNull();
		expect(mateRowMetrics!.contained, 'mobile mate rows should stay inside the demo area').toBe(true);
		expect(mateRowMetrics!.categoryDisplay, 'mate category should remain visible on mobile').not.toBe('none');
		expect(mateRowMetrics!.nameFitsRow, 'mate name should fit inside the active mobile row').toBe(true);
		expect(mateRowMetrics!.categoryFitsRow, 'mate category should fit inside the active mobile row').toBe(true);
		expect(mateRowMetrics!.nameContrast, 'mate name should contrast with its dark-mode row background').toBeGreaterThanOrEqual(MOBILE_TEXT_CONTRAST_MIN);
		expect(mateRowMetrics!.categoryContrast, 'mate category should contrast with its dark-mode row background').toBeGreaterThanOrEqual(MOBILE_TEXT_CONTRAST_MIN);

		await expect(page.getByTestId('landing-mates-focus-demo')).toHaveAttribute('data-active-stage', 'focus', { timeout: 7500 });
		const focusPillMetrics = await page.evaluate(() => {
			const demo = document.querySelector('[data-testid="landing-mates-focus-demo"]')?.getBoundingClientRect();
			const pills = [...document.querySelectorAll<HTMLElement>('[data-testid="landing-focus-mode"]')];
			const active = pills.find((pill) => pill.classList.contains('active')) ?? pills[0];
			const label = active?.querySelector<HTMLElement>('.focus-pill-label-demo');
			const rect = active?.getBoundingClientRect();
			const labelRect = label?.getBoundingClientRect();
			const style = active ? getComputedStyle(active) : null;
			return demo && rect && labelRect && style ? {
				contained: rect.left >= demo.left - 1 && rect.right <= demo.right + 1 && rect.top >= demo.top - 1 && rect.bottom <= demo.bottom + 1,
				labelVisible: labelRect.width >= 90 && labelRect.left >= rect.left && labelRect.right <= rect.right,
				opacity: Number.parseFloat(style.opacity)
			} : null;
		});
		expect(focusPillMetrics).not.toBeNull();
		expect(focusPillMetrics!.contained, 'focus mode pill should stay inside the demo area').toBe(true);
		expect(focusPillMetrics!.labelVisible, 'focus mode label should be visibly positioned inside the pill').toBe(true);
		expect(focusPillMetrics!.opacity, 'active focus mode pill should be readable').toBeGreaterThanOrEqual(0.9);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.actionable-demo-faithful,landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories
	test('tablet landscape keeps Actionable and Privacy animations inside the daily inspiration banner', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(75000);
		await page.setViewportSize({ width: 1024, height: 576 });
		await page.goto(getE2EDebugUrl('/?landing-header-tablet-landscape'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });

		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible();
		await expectInsideBanner(page, 'landing-actionable-event-demo');

		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expectInsideBanner(page, 'landing-privacy-safety-demo');
		for (const stage of PRIVACY_STAGES) {
			await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', stage, {
				timeout: 5000
			});
			const stageTestId = PRIVACY_STAGE_TEST_IDS[stage];
			await expect(page.getByTestId(stageTestId)).toBeVisible();
			await expectInsideBanner(page, stageTestId);
			if (stage === 'encryption-lock' || stage === 'memory-permission') {
				await page.screenshot({ path: testInfo.outputPath(`tablet-landscape-${stage}.png`) });
			}
		}

		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible({ timeout: HEADING_TRANSITION_MS + ADVANCE_GRACE_MS });
		await expectInsideBanner(page, 'landing-mates-focus-demo');
		await expect(page.getByTestId('landing-people-experience-demo')).toBeVisible({ timeout: STORY_DURATION_MS + ADVANCE_GRACE_MS });
		await expectInsideBanner(page, 'landing-people-experience-demo');
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories
	test('tablet portrait keeps every Privacy animation inside the daily inspiration banner', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 768, height: 1024 });
		await openPrivacySlide(page);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {
			timeout: HEADING_SETTLE_MS
		});
		await expectInsideBanner(page, 'landing-privacy-safety-demo');
		for (const stage of PRIVACY_STAGES) {
			await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-active-stage', stage, {
				timeout: 5000
			});
			const stageTestId = PRIVACY_STAGE_TEST_IDS[stage];
			await expect(page.getByTestId(stageTestId)).toBeVisible();
			await expectInsideBanner(page, stageTestId);
		}
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-sequence,landing-onboarding.manual-navigation
	test('guest New chat from an example focuses a blank composer without replaying slide zero', async ({ page }: { page: any }) => {
		test.setTimeout(30000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/#chat-id=example-privacy-first-local-ai'), { waitUntil: 'domcontentloaded' });
		const newChatButton = page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
		await expect(newChatButton).toBeVisible({ timeout: 15000 });
		await newChatButton.click();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeFocused({ timeout: 5000 });
		await expect.poll(async () => page.evaluate(() => window.location.hash)).not.toContain('chat-id=');
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories,landing-onboarding.manual-navigation
	test('reduced motion is static and manually navigable', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await page.setViewportSize({ width: 1280, height: 800 });
		await openPrivacySlide(page, true);

		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-reduced-motion', 'true');
		await expect(page.getByTestId('landing-privacy-safety-demo')).toHaveAttribute('data-playing', 'false');
		await expect(page.getByTestId('landing-privacy-summary')).toBeVisible();
		await expect(page.getByTestId('daily-inspiration-carousel-progress-fill')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
		await page.waitForTimeout(16000);
		await expect(page.getByTestId('landing-privacy-summary')).toBeVisible();
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('landing-mates-focus-demo')).toBeVisible();
	});
});
