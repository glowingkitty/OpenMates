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
	{ name: 'phone-portrait', width: 390, height: 844, minAiIconWidth: 54, maxHeadlineRequestGap: 60, minHeadlineRequestGap: 14, minRequestFontSize: 18, minHighlightedIconWidth: 60, maxHighlightedCenterDelta: 64 },
	{ name: 'ipad-portrait', width: 768, height: 1024, minAiIconWidth: 64, maxHeadlineRequestGap: 54, minHeadlineRequestGap: 4, minRequestFontSize: 18, minHighlightedIconWidth: 68, maxHighlightedCenterDelta: 56 },
	{ name: 'ipad-landscape', width: 1024, height: 768, minAiIconWidth: 58, maxHeadlineRequestGap: 46, minHeadlineRequestGap: 4, minRequestFontSize: 18, minHighlightedIconWidth: 68, maxHighlightedCenterDelta: 64 },
	{ name: 'laptop-landscape', width: 1280, height: 800, minAiIconWidth: 58, maxHeadlineRequestGap: 46, minHeadlineRequestGap: 4, minRequestFontSize: 18, minHighlightedIconWidth: 78, maxHighlightedCenterDelta: 72 },
	{ name: 'full-hd', width: 1920, height: 1080, minAiIconWidth: 74, maxHeadlineRequestGap: 64, minHeadlineRequestGap: 4, minRequestFontSize: 18, minHighlightedIconWidth: 100, maxHighlightedCenterDelta: 90 }
];
const ACTIONABLE_STAGE_SETTLE_MS = 260;
const MOBILE_SLIDE_FADE_SETTLE_MS = 1200;
const ACTIONABLE_INTERACTION_TIMEOUT_MS = 8000;
const LANDING_INTRO_RAIL_SYNC_SETTLE_MS = 760;
const LANDING_INTRO_RAIL_MOTION_SAMPLE_MS = 420;
const PRIMARY_BUTTON_COLOR_TOLERANCE = 4;
const ACTIONABLE_PREVIEW_CENTER_MIN_OFFSET_Y = -24;
const ACTIONABLE_PREVIEW_CENTER_MAX_OFFSET_Y = 15;
const ACTIONABLE_DEMO_MAX_BANNER_OVERFLOW_PX = 26;
const MOBILE_ACTIONABLE_CONTENT_CENTER_MAX_DELTA_X = 12;
const MOBILE_ACTIONABLE_CONTENT_CENTER_MAX_DELTA_Y = 8;
const MOBILE_ACTIONABLE_HEADLINE_MAX_LEFT_GAP = 96;
const DAILY_INSPIRATION_REFERENCE_WIDTH = 373;
const DAILY_INSPIRATION_REFERENCE_HEIGHT = 190;
const DAILY_INSPIRATION_DESKTOP_MIN_HEIGHT = 250;
const DAILY_INSPIRATION_MAX_HEIGHT = 420;
const DAILY_INSPIRATION_MAX_VIEWPORT_HEIGHT_RATIO = 0.35;
const LANDING_INTRO_HEADLINE_TEXT = 'Your AI team\nfor getting things done';
const LANDING_INTRO_REQUESTS = [
	'Find doctor appointments',
	'Find events',
	'Build a web app',
	'Explain the news'
];
const LANDING_INTRO_HIGHLIGHTED_APPS = ['health', 'events', 'code', 'news'];
const LANDING_INTRO_REQUEST_APP_IDS = Object.fromEntries(
	LANDING_INTRO_REQUESTS.map((request, index) => [request, LANDING_INTRO_HIGHLIGHTED_APPS[index]])
);

type ActionableStage = 'user-request' | 'assistant-response' | 'event-preview' | 'luma-cta';

async function skipExpandedLandingIntro(page: any): Promise<void> {
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
}

async function waitForLandingIntroExamples(page: any): Promise<void> {
	let lastError: unknown;
	for (let attempt = 0; attempt < 2; attempt += 1) {
		try {
			await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
			await expect.poll(async () => page.getByTestId('landing-intro-request').textContent(), { timeout: 6000 }).toBeTruthy();
			return;
		} catch (error) {
			lastError = error;
			if (attempt === 0) {
				await page.reload({ waitUntil: 'domcontentloaded' });
				await page.waitForLoadState('networkidle');
			}
		}
	}
	throw lastError;
}

async function getGuestComposerPlaceholder(page: any): Promise<string> {
	return page.getByTestId('message-editor').evaluate((element: HTMLElement) => {
		const paragraph = element.querySelector<HTMLElement>('.ProseMirror p[data-placeholder]');
		return paragraph?.dataset.placeholder ?? '';
	});
}

async function landingIntroLayoutMetrics(page: any): Promise<{
	activeSideGap: number;
	activeBottomGap: number;
	bannerActiveTopDelta: number;
	bannerActiveLeftDelta: number;
	bannerActiveRightDelta: number;
	bannerActiveBottomDelta: number;
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
			bannerActiveTopDelta: Math.abs(bannerRect.top - activeRect.top),
			bannerActiveLeftDelta: Math.abs(bannerRect.left - activeRect.left),
			bannerActiveRightDelta: Math.abs(bannerRect.right - activeRect.right),
			bannerActiveBottomDelta: Math.abs(bannerRect.bottom - activeRect.bottom),
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

async function landingIntroActiveRequestMetrics(page: any): Promise<{
	requestLabel: string;
	expectedAppId: string;
	headlineText: string;
	headlineVisible: boolean;
	requestVisible: boolean;
	requestFontSize: number;
	headlineRequestGap: number;
	highlightedMatchesExpected: boolean;
	highlightedIconVisible: boolean;
	highlightedIconWidth: number;
	highlightedCenterDelta: number;
	primaryVisibleIconCount: number;
	primaryMinIconGap: number;
	primaryAnimationName: string;
	primaryAnimationDurationMs: number;
	primaryAnimationPlayState: string;
	primaryHighlightedIndexes: number[];
	secondaryVisibleIconCount: number;
	secondaryMinIconGap: number;
	secondaryAnimationName: string;
	secondaryAnimationDurationMs: number;
	secondaryAnimationPlayState: string;
}> {
	return page.evaluate(({ requestAppIds, highlightedAppIds }: { requestAppIds: Record<string, string>; highlightedAppIds: string[] }) => {
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const headline = document.querySelector<HTMLElement>('[data-testid="landing-intro-headline"]');
		const request = document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]');
		const rails = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'));
		const primaryRail = rails[0];
		const secondaryRail = rails[1];
		if (!banner || !headline || !request || !primaryRail || !secondaryRail) {
			throw new Error('Landing intro active request elements missing');
		}

		const bannerRect = banner.getBoundingClientRect();
		const headlineRect = headline.getBoundingClientRect();
		const requestRect = request.getBoundingClientRect();
		const requestLabel = request.textContent?.trim() || '';
		const expectedAppId = requestAppIds[requestLabel] || '';
		const requestCenterX = requestRect.left + requestRect.width / 2;
		const primaryHighlightedIcons = Array.from(primaryRail.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"][data-highlighted="true"]'));
		const expectedHighlightedIcons = primaryHighlightedIcons.filter((icon) => icon.getAttribute('data-app-id') === expectedAppId);
		const highlightedRects = expectedHighlightedIcons.map((icon) => icon.getBoundingClientRect());
		const visibleHighlightedRects = highlightedRects.filter((rect) => (
			rect.left >= bannerRect.left - 1
			&& rect.right <= bannerRect.right + 1
			&& rect.top >= bannerRect.top - 1
			&& rect.bottom <= bannerRect.bottom + 1
		));

		function rowMetrics(rail: HTMLElement): { visibleIconCount: number; minIconGap: number } {
			const visibleRects = Array.from(rail.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"]'))
				.map((icon) => icon.getBoundingClientRect())
				.filter((rect) => rect.right > bannerRect.left && rect.left < bannerRect.right)
				.sort((a, b) => a.left - b.left);
			let minIconGap = Number.POSITIVE_INFINITY;
			for (let index = 1; index < visibleRects.length; index += 1) {
				minIconGap = Math.min(minIconGap, visibleRects[index].left - visibleRects[index - 1].right);
			}
			return {
				visibleIconCount: visibleRects.length,
				minIconGap: Number.isFinite(minIconGap) ? minIconGap : 999
			};
		}

		function animationDurationMs(value: string): number {
			const firstDuration = value.split(',')[0]?.trim() || '0s';
			if (firstDuration.endsWith('ms')) return Number.parseFloat(firstDuration);
			if (firstDuration.endsWith('s')) return Number.parseFloat(firstDuration) * 1000;
			return Number.parseFloat(firstDuration) || 0;
		}

		const primaryMetrics = rowMetrics(primaryRail);
		const secondaryMetrics = rowMetrics(secondaryRail);
		const primaryStyle = getComputedStyle(primaryRail);
		const secondaryStyle = getComputedStyle(secondaryRail);
		const primaryIcons = Array.from(primaryRail.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"]'));
		const primaryHighlightedIndexes = highlightedAppIds.map((appId) => (
			primaryIcons.findIndex((icon) => icon.getAttribute('data-app-id') === appId)
		));
		const highlightedCenterDeltas = visibleHighlightedRects.map((rect) => Math.abs((rect.left + rect.width / 2) - requestCenterX));
		const highlightedWidths = visibleHighlightedRects.map((rect) => rect.width);
		return {
			requestLabel,
			expectedAppId,
			headlineText: headline.innerText.trim(),
			headlineVisible: headlineRect.top >= bannerRect.top - 1 && headlineRect.bottom <= bannerRect.bottom + 1,
			requestVisible: requestRect.top >= bannerRect.top - 1 && requestRect.bottom <= bannerRect.bottom + 1,
			requestFontSize: Number.parseFloat(getComputedStyle(request).fontSize),
			headlineRequestGap: requestRect.top - headlineRect.bottom,
			highlightedMatchesExpected: expectedHighlightedIcons.length > 0,
			highlightedIconVisible: visibleHighlightedRects.length > 0,
			highlightedIconWidth: highlightedWidths.length > 0 ? Math.max(...highlightedWidths) : 0,
			highlightedCenterDelta: highlightedCenterDeltas.length > 0 ? Math.min(...highlightedCenterDeltas) : Number.POSITIVE_INFINITY,
			primaryVisibleIconCount: primaryMetrics.visibleIconCount,
			primaryMinIconGap: primaryMetrics.minIconGap,
			primaryAnimationName: primaryStyle.animationName,
			primaryAnimationDurationMs: animationDurationMs(primaryStyle.animationDuration),
			primaryAnimationPlayState: primaryStyle.animationPlayState,
			primaryHighlightedIndexes,
			secondaryVisibleIconCount: secondaryMetrics.visibleIconCount,
			secondaryMinIconGap: secondaryMetrics.minIconGap,
			secondaryAnimationName: secondaryStyle.animationName,
			secondaryAnimationDurationMs: animationDurationMs(secondaryStyle.animationDuration),
			secondaryAnimationPlayState: secondaryStyle.animationPlayState
		};
	}, { requestAppIds: LANDING_INTRO_REQUEST_APP_IDS, highlightedAppIds: LANDING_INTRO_HIGHLIGHTED_APPS });
}

async function collectLandingIntroCycleMetrics(page: any): Promise<Map<string, Awaited<ReturnType<typeof landingIntroActiveRequestMetrics>>>> {
	const seen = new Map<string, Awaited<ReturnType<typeof landingIntroActiveRequestMetrics>>>();
	const deadline = Date.now() + 13000;
	while (seen.size < LANDING_INTRO_REQUESTS.length && Date.now() < deadline) {
		const currentLabel = await page.evaluate(() => (
			document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]')?.textContent?.trim() || ''
		));
		if (LANDING_INTRO_REQUESTS.includes(currentLabel) && !seen.has(currentLabel)) {
			await page.waitForTimeout(LANDING_INTRO_RAIL_SYNC_SETTLE_MS);
			const metrics = await landingIntroActiveRequestMetrics(page);
			if (metrics.requestLabel === currentLabel) {
				seen.set(currentLabel, metrics);
			}
		}
		await page.waitForTimeout(100);
	}
	return seen;
}

async function landingIntroRailPositionSnapshot(page: any): Promise<{
	requestLabel: string;
	primaryLeft: number;
	secondaryLeft: number;
}> {
	return page.evaluate(() => {
		const request = document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]');
		const rails = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'));
		const primaryRail = rails[0];
		const secondaryRail = rails[1];
		if (!request || !primaryRail || !secondaryRail) {
			throw new Error('Landing intro rail motion elements missing');
		}

		return {
			requestLabel: request.textContent?.trim() || '',
			primaryLeft: primaryRail.getBoundingClientRect().left,
			secondaryLeft: secondaryRail.getBoundingClientRect().left
		};
	});
}

async function landingIntroRailMotionMetrics(page: any): Promise<{
	requestLabel: string;
	primaryDeltaX: number;
	secondaryDeltaX: number;
}> {
	for (let attempt = 0; attempt < 5; attempt += 1) {
		await page.waitForTimeout(LANDING_INTRO_RAIL_SYNC_SETTLE_MS);
		const before = await landingIntroRailPositionSnapshot(page);
		await page.waitForTimeout(LANDING_INTRO_RAIL_MOTION_SAMPLE_MS);
		const after = await landingIntroRailPositionSnapshot(page);
		if (before.requestLabel === after.requestLabel) {
			return {
				requestLabel: before.requestLabel,
				primaryDeltaX: after.primaryLeft - before.primaryLeft,
				secondaryDeltaX: after.secondaryLeft - before.secondaryLeft
			};
		}
	}

	throw new Error('Landing intro request changed during rail motion sampling');
}

async function landingIntroRailSwitchMotionMetrics(page: any): Promise<{
	requestBefore: string;
	requestAfter: string;
	primaryRailStable: boolean;
	primaryDeltaX: number;
	secondaryDeltaX: number;
}> {
	return page.evaluate(async ({ sampleMs, timeoutMs }: { sampleMs: number; timeoutMs: number }) => {
		const request = document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]');
		const rails = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'));
		const primaryRail = rails[0];
		const secondaryRail = rails[1];
		if (!request || !primaryRail || !secondaryRail) {
			throw new Error('Landing intro rail switch elements missing');
		}

		const requestBefore = request.textContent?.trim() || '';
		const deadline = performance.now() + timeoutMs;
		await new Promise<void>((resolve, reject) => {
			const waitForSwitch = () => {
				const currentRequest = request.textContent?.trim() || '';
				if (currentRequest && currentRequest !== requestBefore) {
					resolve();
					return;
				}
				if (performance.now() >= deadline) {
					reject(new Error('Landing intro request did not switch before timeout'));
					return;
				}
				requestAnimationFrame(waitForSwitch);
			};
			requestAnimationFrame(waitForSwitch);
		});

		const primaryStart = primaryRail.getBoundingClientRect().left;
		const secondaryStart = secondaryRail.getBoundingClientRect().left;
		await new Promise<void>((resolve) => window.setTimeout(resolve, sampleMs));
		const currentRails = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'));

		return {
			requestBefore,
			requestAfter: request.textContent?.trim() || '',
			primaryRailStable: currentRails[0] === primaryRail,
			primaryDeltaX: primaryRail.getBoundingClientRect().left - primaryStart,
			secondaryDeltaX: secondaryRail.getBoundingClientRect().left - secondaryStart
		};
	}, { sampleMs: LANDING_INTRO_RAIL_MOTION_SAMPLE_MS, timeoutMs: 4000 });
}

async function landingIntroOverlayMetrics(page: any): Promise<{
	phase: string | null;
	activeHeight: number;
	areaHeight: number;
	bannerHeight: number;
	bannerActiveTopDelta: number;
	bannerActiveLeftDelta: number;
	bannerActiveRightDelta: number;
	bannerActiveBottomDelta: number;
	messageInputOpacity: number;
	welcomeContentOpacity: number;
	introContentOpacity: number | null;
	messageInputExists: boolean;
}> {
	return page.evaluate(() => {
		const active = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
		const area = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-area"]');
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const messageInput = document.querySelector<HTMLElement>('[data-testid="message-input-wrapper"]');
		const welcomeContent = document.querySelector<HTMLElement>('[data-testid="welcome-content"]');
		const introContent = document.querySelector<HTMLElement>('[data-testid="landing-intro-expanded"]');
		if (!active || !area || !banner || !messageInput || !welcomeContent) {
			throw new Error('Landing intro overlay elements missing');
		}

		const activeRect = active.getBoundingClientRect();
		const areaRect = area.getBoundingClientRect();
		const bannerRect = banner.getBoundingClientRect();
		return {
			phase: banner.getAttribute('data-landing-intro-phase'),
			activeHeight: activeRect.height,
			areaHeight: areaRect.height,
			bannerHeight: bannerRect.height,
			bannerActiveTopDelta: Math.abs(bannerRect.top - activeRect.top),
			bannerActiveLeftDelta: Math.abs(bannerRect.left - activeRect.left),
			bannerActiveRightDelta: Math.abs(bannerRect.right - activeRect.right),
			bannerActiveBottomDelta: Math.abs(bannerRect.bottom - activeRect.bottom),
			messageInputOpacity: Number.parseFloat(getComputedStyle(messageInput).opacity),
			welcomeContentOpacity: Number.parseFloat(getComputedStyle(welcomeContent).opacity),
			introContentOpacity: introContent ? Number.parseFloat(getComputedStyle(introContent).opacity) : null,
			messageInputExists: true
		};
	});
}

async function waitForExpandedIntroToCoverActiveChat(page: any): Promise<void> {
	await expect.poll(async () => (await landingIntroOverlayMetrics(page)).phase, { timeout: 5000 }).toBe('expanded');
	await expect.poll(async () => (await landingIntroOverlayMetrics(page)).bannerActiveBottomDelta, { timeout: 5000 }).toBeLessThanOrEqual(2);
}

async function guestExploreLayoutMetrics(page: any): Promise<{
	promptText: string;
	promptTop: number;
	carouselTop: number;
	firstCardTop: number;
	linkRowTop: number;
}> {
	return page.evaluate(() => {
		const prompt = document.querySelector<HTMLElement>('[data-testid="guest-interest-prompt"]');
		const carousel = document.querySelector<HTMLElement>('[data-testid="recent-chats-scroll-container"]');
		const firstCard = document.querySelector<HTMLElement>('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]');
		const linkRow = document.querySelector<HTMLElement>('[data-testid="guest-example-link-row"]');
		if (!prompt || !carousel || !firstCard || !linkRow) {
			throw new Error('Guest explore layout elements missing');
		}

		return {
			promptText: prompt.textContent?.trim() ?? '',
			promptTop: prompt.getBoundingClientRect().top,
			carouselTop: carousel.getBoundingClientRect().top,
			firstCardTop: firstCard.getBoundingClientRect().top,
			linkRowTop: linkRow.getBoundingClientRect().top
		};
	});
}

function expectStableGuestExploreLayout(before: Awaited<ReturnType<typeof guestExploreLayoutMetrics>>, after: Awaited<ReturnType<typeof guestExploreLayoutMetrics>>): void {
	expect(Math.abs(after.promptTop - before.promptTop), 'guest prompt must not move while slide 0 changes to slide 1').toBeLessThanOrEqual(2);
	expect(Math.abs(after.carouselTop - before.carouselTop), 'example carousel must not move while slide 0 changes to slide 1').toBeLessThanOrEqual(2);
	expect(Math.abs(after.firstCardTop - before.firstCardTop), 'first example card must not move while slide 0 changes to slide 1').toBeLessThanOrEqual(2);
	expect(Math.abs(after.linkRowTop - before.linkRowTop), 'example links must not move while slide 0 changes to slide 1').toBeLessThanOrEqual(2);
}

async function waitForActionableStage(page: any, stage: ActionableStage): Promise<void> {
	await expect.poll(
		async () => page.getByTestId('landing-actionable-event-demo').getAttribute('data-active-stage'),
		{ timeout: 12000 }
	).toBe(stage);
	await page.waitForTimeout(ACTIONABLE_STAGE_SETTLE_MS);
}

async function actionableStageState(page: any): Promise<{
	activeStage: string | null;
	interactionState: string | null;
	stageCount: number;
	hasUserMessage: boolean;
	hasAssistantMessage: boolean;
	hasPreview: boolean;
	hasCtaCard: boolean;
	hasButton: boolean;
	hasPointer: boolean;
	buttonText: string;
	buttonBackground: string;
}> {
	return page.getByTestId('landing-actionable-event-demo').evaluate((demo: HTMLElement) => {
		const button = demo.querySelector<HTMLElement>('[data-testid="landing-actionable-luma-button"]');
		return {
			activeStage: demo.getAttribute('data-active-stage'),
			interactionState: demo.getAttribute('data-interaction-state'),
			stageCount: demo.querySelectorAll('[data-testid="landing-actionable-stage"]').length,
			hasUserMessage: Boolean(demo.querySelector('[data-testid="landing-actionable-user-message"]')),
			hasAssistantMessage: Boolean(demo.querySelector('[data-testid="landing-actionable-assistant-message"]')),
			hasPreview: Boolean(demo.querySelector('[data-testid="landing-actionable-event-preview"]')),
			hasCtaCard: Boolean(demo.querySelector('[data-testid="landing-actionable-event-cta-card"]')),
			hasButton: Boolean(button),
			hasPointer: Boolean(demo.querySelector('[data-testid="landing-actionable-pointer"]')),
			buttonText: button?.textContent?.trim() ?? '',
			buttonBackground: button ? getComputedStyle(button).backgroundColor : ''
		};
	});
}

async function mobileActionableSlideState(page: any): Promise<{
	bannerHeight: number;
	bannerTop: number;
	bannerBottom: number;
	headingCount: number;
	headlineFontSize: number;
	copyTop: number;
	headlineLeftGap: number;
	iconCount: number;
	demoCount: number;
	demoOpacity: number;
	demoBottom: number;
	demoHeight: number;
	demoBackground: string;
	demoBorderWidth: string;
	demoBoxShadow: string;
	demoContentCenterDeltaX: number;
	demoContentCenterDeltaY: number;
	reportButtonTop: number;
}> {
	return page.evaluate(() => {
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const headline = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-phrase"]');
		const copy = document.querySelector<HTMLElement>('[data-testid="guest-intro-copy"]');
		const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
		const stage = document.querySelector<HTMLElement>('[data-testid="landing-actionable-stage"]');
		const reportButton = document.querySelector<HTMLElement>('[data-testid="report-issue-button"]');
		if (!banner || !reportButton) throw new Error('mobile actionable slide elements missing');

		const bannerRect = banner.getBoundingClientRect();
		const headlineRect = headline?.getBoundingClientRect();
		const copyRect = copy?.getBoundingClientRect();
		const demoRect = demo?.getBoundingClientRect();
		const stageContentRect = stage?.querySelector<HTMLElement>('[data-testid="landing-actionable-stage-content"]')
			?.firstElementChild?.getBoundingClientRect();
		const demoCenterX = demoRect ? demoRect.left + demoRect.width / 2 : bannerRect.left + bannerRect.width / 2;
		const demoCenterY = demoRect ? demoRect.top + demoRect.height / 2 : bannerRect.top + bannerRect.height / 2;
		const contentCenterX = stageContentRect ? stageContentRect.left + stageContentRect.width / 2 : demoCenterX;
		const contentCenterY = stageContentRect ? stageContentRect.top + stageContentRect.height / 2 : demoCenterY;
		const demoStyle = demo ? getComputedStyle(demo) : null;
		return {
			bannerHeight: bannerRect.height,
			bannerTop: bannerRect.top,
			bannerBottom: bannerRect.bottom,
			headingCount: headline ? 1 : 0,
			headlineFontSize: headline ? Number.parseFloat(getComputedStyle(headline).fontSize) : 0,
			copyTop: copyRect?.top ?? 0,
			headlineLeftGap: headlineRect ? headlineRect.left - bannerRect.left : 0,
			iconCount: document.querySelectorAll('[data-testid="guest-feature-inline-icon"]').length,
			demoCount: demo ? 1 : 0,
			demoOpacity: demoStyle ? Number.parseFloat(demoStyle.opacity) : 0,
			demoBottom: demoRect?.bottom ?? 0,
			demoHeight: demoRect?.height ?? 0,
			demoBackground: demoStyle?.backgroundColor ?? '',
			demoBorderWidth: demoStyle?.borderTopWidth ?? '',
			demoBoxShadow: demoStyle?.boxShadow ?? '',
			demoContentCenterDeltaX: Math.abs(contentCenterX - demoCenterX),
			demoContentCenterDeltaY: Math.abs(contentCenterY - demoCenterY),
			reportButtonTop: reportButton.getBoundingClientRect().top
		};
	});
}

test.describe('Landing page onboarding refresh', () => {
	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.intro-active-apps-only,landing-onboarding.coordinated-story-progress
	test('expanded intro fits all target device viewports', async ({ page }: { page: any }) => {
		test.setTimeout(180000);

		for (const viewport of LANDING_INTRO_VIEWPORTS) {
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			await page.goto(getE2EDebugUrl(`/?landing-layout=${viewport.name}`), { waitUntil: 'domcontentloaded' });
			const requestSamplesPromise = collectLandingIntroCycleMetrics(page);
			await page.waitForLoadState('networkidle');
			await waitForLandingIntroExamples(page);
			await waitForExpandedIntroToCoverActiveChat(page);

			const metrics = await landingIntroLayoutMetrics(page);
			expect(metrics.activeBottomGap, `${viewport.name}: bottom gap should match side gap`).toBeLessThanOrEqual(metrics.activeSideGap + 3);
			expect(metrics.activeBottomGap, `${viewport.name}: bottom gap should not collapse`).toBeGreaterThanOrEqual(Math.max(0, metrics.activeSideGap - 3));
			expect(metrics.bannerActiveTopDelta, `${viewport.name}: expanded banner must cover active chat top`).toBeLessThanOrEqual(2);
			expect(metrics.bannerActiveLeftDelta, `${viewport.name}: expanded banner must cover active chat left`).toBeLessThanOrEqual(2);
			expect(metrics.bannerActiveRightDelta, `${viewport.name}: expanded banner must cover active chat right`).toBeLessThanOrEqual(2);
			expect(metrics.bannerActiveBottomDelta, `${viewport.name}: expanded banner must cover active chat bottom`).toBeLessThanOrEqual(2);
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

			const requestSamples = await requestSamplesPromise;
			expect(Array.from(requestSamples.keys()), `${viewport.name}: should sample every intro request`).toEqual(LANDING_INTRO_REQUESTS);
			for (const requestLabel of LANDING_INTRO_REQUESTS) {
				const sample = requestSamples.get(requestLabel);
				expect(sample, `${viewport.name}: missing sample for ${requestLabel}`).toBeTruthy();
				if (!sample) continue;
				expect(sample.primaryAnimationName, `${viewport.name}: primary rail should move right-to-left`).toContain('landingIntroRailLeft');
				expect(sample.secondaryAnimationName, `${viewport.name}: secondary rail should move left-to-right`).toContain('landingIntroRailRight');
				expect(sample.primaryAnimationPlayState, `${viewport.name}: primary rail animation should run`).toContain('running');
				expect(sample.secondaryAnimationPlayState, `${viewport.name}: secondary rail animation should run`).toContain('running');
				expect(sample.primaryAnimationDurationMs, `${viewport.name}: primary rail should be slower than secondary`).toBeGreaterThan(sample.secondaryAnimationDurationMs);
				expect(sample.primaryHighlightedIndexes, `${viewport.name}: highlighted app placeholders should be removed`).toEqual([0, 1, 2, 3]);
				expect(sample.headlineText, `${viewport.name}: headline text`).toBe(LANDING_INTRO_HEADLINE_TEXT);
				expect(sample.headlineVisible, `${viewport.name}: heading visible during ${requestLabel}`).toBe(true);
				expect(sample.requestVisible, `${viewport.name}: user message visible during ${requestLabel}`).toBe(true);
				expect(sample.requestFontSize, `${viewport.name}: user message too small during ${requestLabel}`).toBeGreaterThanOrEqual(viewport.minRequestFontSize);
				expect(sample.headlineRequestGap, `${viewport.name}: heading/message gap too small during ${requestLabel}`).toBeGreaterThanOrEqual(viewport.minHeadlineRequestGap);
				expect(sample.expectedAppId, `${viewport.name}: expected app mapping for ${requestLabel}`).toBeTruthy();
				expect(sample.highlightedMatchesExpected, `${viewport.name}: highlighted app id should match ${requestLabel}`).toBe(true);
				expect(sample.highlightedIconVisible, `${viewport.name}: highlighted ${sample.expectedAppId} icon should be visible during ${requestLabel}`).toBe(true);
				expect(sample.highlightedIconWidth, `${viewport.name}: highlighted ${sample.expectedAppId} icon too small during ${requestLabel}`).toBeGreaterThanOrEqual(viewport.minHighlightedIconWidth);
				expect(sample.highlightedCenterDelta, `${viewport.name}: highlighted ${sample.expectedAppId} icon should sit under the user message during ${requestLabel}`).toBeLessThanOrEqual(viewport.maxHighlightedCenterDelta);
				expect(sample.primaryVisibleIconCount, `${viewport.name}: primary row visible icon count during ${requestLabel}`).toBeGreaterThanOrEqual(5);
				expect(sample.secondaryVisibleIconCount, `${viewport.name}: secondary row visible icon count during ${requestLabel}`).toBeGreaterThanOrEqual(5);
				expect(sample.primaryMinIconGap, `${viewport.name}: primary row icons overlap during ${requestLabel}`).toBeGreaterThanOrEqual(1);
				expect(sample.secondaryMinIconGap, `${viewport.name}: secondary row icons overlap during ${requestLabel}`).toBeGreaterThanOrEqual(1);
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.intro-active-apps-only,landing-onboarding.coordinated-story-progress
	test('expanded intro app rails keep moving with a slower primary row', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/?landing-rail-motion'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);

		const metrics = await landingIntroRailMotionMetrics(page);
		expect(metrics.requestLabel, 'motion sample should happen during a visible request').toBeTruthy();
		expect(metrics.primaryDeltaX, 'primary rail should keep moving right-to-left').toBeLessThan(-1);
		expect(metrics.secondaryDeltaX, 'secondary rail should keep moving left-to-right').toBeGreaterThan(1);
		expect(Math.abs(metrics.primaryDeltaX), 'primary rail should move slower than secondary').toBeLessThan(Math.abs(metrics.secondaryDeltaX));
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.intro-active-apps-only,landing-onboarding.coordinated-story-progress
	test('expanded intro top app rail stays continuous when the highlighted app switches', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/?landing-rail-switch-motion'), { waitUntil: 'domcontentloaded' });
		await waitForLandingIntroExamples(page);
		const railSwitchMetricsPromise = landingIntroRailSwitchMotionMetrics(page);
		await page.waitForLoadState('networkidle');

		const metrics = await railSwitchMetricsPromise;
		expect(metrics.requestAfter, 'request should advance to the next app').not.toBe(metrics.requestBefore);
		expect(metrics.primaryRailStable, 'app switch should preserve the same top rail node').toBe(true);
		expect(metrics.primaryDeltaX, 'top rail should keep moving right-to-left through the app switch').toBeLessThan(-1);
		expect(metrics.secondaryDeltaX, 'bottom rail should keep moving left-to-right through the app switch').toBeGreaterThan(1);
		expect(Math.abs(metrics.primaryDeltaX), 'top rail should not accelerate past the bottom rail during the app switch').toBeLessThanOrEqual(Math.abs(metrics.secondaryDeltaX));
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-sequence,landing-onboarding.manual-navigation
	test('expanded intro overlays active chat content and reverses when returning to slide one', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/?landing-overlay-contract'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await waitForExpandedIntroToCoverActiveChat(page);

		const expanded = await landingIntroOverlayMetrics(page);
		expect(expanded.phase).toBe('expanded');
		expect(expanded.messageInputExists, 'message input stays mounted under the overlay').toBe(true);
		expect(expanded.bannerActiveTopDelta, 'expanded intro covers active chat top').toBeLessThanOrEqual(2);
		expect(expanded.bannerActiveLeftDelta, 'expanded intro covers active chat left').toBeLessThanOrEqual(2);
		expect(expanded.bannerActiveRightDelta, 'expanded intro covers active chat right').toBeLessThanOrEqual(2);
		expect(expanded.bannerActiveBottomDelta, 'expanded intro covers active chat bottom').toBeLessThanOrEqual(2);
		expect(expanded.areaHeight, 'expanded intro keeps the in-flow banner reserve at regular height').toBeLessThan(expanded.activeHeight * 0.55);
		expect(expanded.messageInputOpacity, 'message input is transparent while covered').toBeLessThanOrEqual(0.05);
		expect(expanded.welcomeContentOpacity, 'welcome content is transparent while covered').toBeLessThanOrEqual(0.05);

		await page.getByTestId('daily-inspiration-next').click();
		await expect.poll(async () => {
			const phase = (await landingIntroOverlayMetrics(page)).phase;
			return phase === 'fading-out' || phase === 'collapsing';
		}, { timeout: 1000 }).toBe(true);
		await expect.poll(async () => {
			const opacity = (await landingIntroOverlayMetrics(page)).introContentOpacity;
			return opacity === null || opacity < 0.2;
		}, { timeout: 1500 }).toBe(true);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).phase, { timeout: 2000 }).toBe('collapsing');
		await expect(page.getByTestId('landing-actionable-event-demo')).toHaveCount(0);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).messageInputOpacity, { timeout: 1500 }).toBeGreaterThan(0.2);
		const collapsing = await landingIntroOverlayMetrics(page);
		expect(collapsing.areaHeight, 'collapsing intro keeps lower welcome layout reserve stable').toBeLessThan(collapsing.activeHeight * 0.55);
		expect(collapsing.messageInputOpacity, 'message input fades in while intro shrinks').toBeGreaterThan(0.2);
		expect(collapsing.welcomeContentOpacity, 'welcome content fades in while intro shrinks').toBeGreaterThan(0.2);

		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).phase, { timeout: 2000 }).toBe('regular');
		const regular = await landingIntroOverlayMetrics(page);
		expect(regular.phase).toBe('regular');
		expect(regular.bannerHeight, 'regular daily inspiration respects the compact max height').toBeLessThanOrEqual(DAILY_INSPIRATION_MAX_HEIGHT);
		expect(regular.bannerHeight, 'regular daily inspiration is smaller than the active chat').toBeLessThan(regular.activeHeight);
		expect(regular.messageInputOpacity, 'message input is visible after collapse').toBeGreaterThanOrEqual(0.95);
		expect(regular.welcomeContentOpacity, 'welcome content is visible after collapse').toBeGreaterThanOrEqual(0.95);

		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 5000 });
		await waitForExpandedIntroToCoverActiveChat(page);
		const restored = await landingIntroOverlayMetrics(page);
		expect(restored.bannerActiveBottomDelta, 'returning to slide one expands over active chat bottom').toBeLessThanOrEqual(2);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).messageInputOpacity, { timeout: 2000 }).toBeLessThanOrEqual(0.05);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).welcomeContentOpacity, { timeout: 2000 }).toBeLessThanOrEqual(0.05);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.manual-navigation
	test('touch guest prompt and example cards stay fixed when intro advances to slide two', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 768, height: 1024 });
		await page.addInitScript(() => {
			Object.defineProperty(navigator, 'maxTouchPoints', {
				configurable: true,
				get: () => 5
			});
			Object.defineProperty(window, 'ontouchstart', {
				configurable: true,
				value: null
			});
		});

		await page.goto(getE2EDebugUrl('/?landing-touch-stable-examples'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await waitForExpandedIntroToCoverActiveChat(page);

		await page.getByTestId('daily-inspiration-next').click();
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).phase, { timeout: 2000 }).toBe('collapsing');
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).welcomeContentOpacity, { timeout: 1500 }).toBeGreaterThan(0.2);
		const collapsing = await guestExploreLayoutMetrics(page);
		expect(collapsing.promptText).toContain('Tap or swipe, to explore real chats:');

		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		const regular = await guestExploreLayoutMetrics(page);
		expect(regular.promptText).toContain('Tap or swipe, to explore real chats:');
		expectStableGuestExploreLayout(collapsing, regular);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('settings stays beside active chat on laptop', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1440, height: 900 });
		const exampleChatId = 'example-berlin-dermatology-appointments';

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', exampleChatId, { timeout: 15000 });
		await expect(page.getByTestId('mate-message-content').last()).toContainText('dermatology', { timeout: 15000 });

		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });
		await expect.poll(
			async () => page.getByTestId('settings-menu').evaluate((element: HTMLElement) => element.getBoundingClientRect().width),
			{ timeout: 3000 }
		).toBeGreaterThan(300);
		await expect.poll(
			async () => page.getByTestId('settings-menu').evaluate((element: HTMLElement) => getComputedStyle(element).position),
			{ timeout: 3000 }
		).not.toBe('fixed');
		await expect.poll(
			async () => page.getByTestId('active-chat-container').evaluate((element: HTMLElement) => element.classList.contains('dimmed')),
			{ timeout: 3000 }
		).toBe(false);

		const laptopLayout = await page.evaluate(() => {
			const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
			const settings = document.querySelector<HTMLElement>('[data-testid="settings-menu"]');
			if (!activeChat || !settings) throw new Error('Expected active chat and settings panel');
			const activeChatRect = activeChat.getBoundingClientRect();
			const settingsRect = settings.getBoundingClientRect();
			return {
				activeChatBottom: activeChatRect.bottom,
				activeChatRight: activeChatRect.right,
				activeChatOverflowY: getComputedStyle(activeChat).overflowY,
				settingsLeft: settingsRect.left,
				settingsRight: settingsRect.right,
				viewportHeight: window.innerHeight
			};
		});
		expect(laptopLayout.activeChatOverflowY, 'active chat itself must not become vertically scrollable').toBe('hidden');
		expect(laptopLayout.activeChatBottom, 'settings panel must not push active chat below the viewport').toBeLessThanOrEqual(
			laptopLayout.viewportHeight - 1
		);
		expect(laptopLayout.activeChatRight, 'laptop settings must sit beside active chat without overlap').toBeLessThanOrEqual(
			laptopLayout.settingsLeft + 1
		);
		expect(laptopLayout.settingsRight, 'laptop settings must remain inside the viewport').toBeLessThanOrEqual(1440);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('settings overlays active chat only on narrow viewports', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1100, height: 800 });

		await page.goto(getE2EDebugUrl('/?settings-active-chat-narrow-layout'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });
		await expect.poll(
			async () => page.getByTestId('settings-menu').evaluate((element: HTMLElement) => getComputedStyle(element).position),
			{ timeout: 3000 }
		).toBe('fixed');
		await expect.poll(
			async () => page.getByTestId('active-chat-container').evaluate((element: HTMLElement) => element.classList.contains('dimmed')),
			{ timeout: 3000 }
		).toBe(true);
		await expect.poll(
			async () => page.getByTestId('settings-menu').evaluate((element: HTMLElement) => element.getBoundingClientRect().right),
			{ message: 'narrow settings overlay must remain inside the viewport', timeout: 3000 }
		).toBeLessThanOrEqual(1100);

		await page.setViewportSize({ width: 1101, height: 800 });
		await expect.poll(
			async () => page.getByTestId('settings-menu').evaluate((element: HTMLElement) => getComputedStyle(element).position),
			{ timeout: 3000 }
		).not.toBe('fixed');
		await expect.poll(
			async () => page.getByTestId('active-chat-container').evaluate((element: HTMLElement) => element.classList.contains('dimmed')),
			{ timeout: 3000 }
		).toBe(false);
		await expect.poll(async () => page.evaluate(() => {
			const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
			const settings = document.querySelector<HTMLElement>('[data-testid="settings-menu"]');
			if (!activeChat || !settings) return true;
			return activeChat.getBoundingClientRect().right > settings.getBoundingClientRect().left + 1;
		}), { message: 'first split-layout width must not overlap active chat', timeout: 3000 }).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.actionable-demo-faithful,landing-onboarding.coordinated-story-progress,landing-onboarding.manual-navigation
	test('actionable slide plays one localized pointer-driven sequence and advances once', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Not just a wall of text.', { timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible({ timeout: 5000 });
		const progressDurationMs = await page.getByTestId('daily-inspiration-carousel-progress').evaluate((progress: HTMLElement) => (
			Number.parseFloat(getComputedStyle(progress).getPropertyValue('--carousel-progress-duration'))
		));
		expect(progressDurationMs, 'Actionable progress must use the one-shot animation duration instead of the generic 20 seconds').toBeLessThan(12000);

		await waitForActionableStage(page, 'user-request');
		let state = await actionableStageState(page);
		expect(state.stageCount, 'only the active request stage should be mounted after transition settle').toBe(1);
		expect(state.hasUserMessage).toBe(true);
		expect(state.hasAssistantMessage).toBe(false);
		expect(state.hasPreview).toBe(false);
		expect(state.hasButton).toBe(false);
		await expect(page.getByTestId('landing-actionable-user-message')).toContainText('Find tech events in Berlin');

		await waitForActionableStage(page, 'assistant-response');
		state = await actionableStageState(page);
		expect(state.stageCount, 'only the active assistant stage should be mounted after transition settle').toBe(1);
		expect(state.hasUserMessage).toBe(false);
		expect(state.hasAssistantMessage).toBe(true);
		expect(state.hasPreview).toBe(false);
		expect(state.hasButton).toBe(false);
		await expect(page.getByTestId('landing-actionable-assistant-profile')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-actionable-assistant-name')).toHaveText('George');
		await expect(page.getByTestId('landing-actionable-assistant-message')).toContainText('Of course, here you go:');

		await waitForActionableStage(page, 'event-preview');
		state = await actionableStageState(page);
		expect(state.stageCount, 'only the active event preview stage should be mounted after transition settle').toBe(1);
		expect(state.hasUserMessage).toBe(false);
		expect(state.hasAssistantMessage).toBe(false);
		expect(state.hasPreview).toBe(true);
		expect(state.hasButton).toBe(false);
		await expect(page.getByTestId('landing-actionable-event-preview')).toContainText('DEPIN DAY BERLIN');
		await expect(page.getByTestId('landing-actionable-event-preview').getByTestId('embed-preview')).toHaveAttribute(
			'data-app-id',
			'events'
		);
		await expect(page.getByTestId('landing-actionable-pointer')).toBeVisible({ timeout: ACTIONABLE_INTERACTION_TIMEOUT_MS });
		await expect.poll(
			async () => page.getByTestId('landing-actionable-event-demo').getAttribute('data-interaction-state'),
			{ timeout: ACTIONABLE_INTERACTION_TIMEOUT_MS }
		).toBe('preview-clicked');
		await expect(page.getByTestId('landing-actionable-event-preview')).toHaveAttribute('data-demo-pressed', 'true');
		const previewGeometry = await page.evaluate(() => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const scene = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-scene"]');
			const preview = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-preview"]');
			const pointer = document.querySelector<HTMLElement>('[data-testid="landing-actionable-pointer"]');
			if (!banner || !scene || !preview || !pointer) throw new Error('Actionable preview geometry elements missing');
			const bannerRect = banner.getBoundingClientRect();
			const sceneRect = scene.getBoundingClientRect();
			const previewRect = preview.getBoundingClientRect();
			return {
				centerDeltaX: Math.abs((previewRect.left + previewRect.width / 2) - (sceneRect.left + sceneRect.width / 2)),
				centerOffsetY: (previewRect.top + previewRect.height / 2) - (sceneRect.top + sceneRect.height / 2),
				pointerInsideScene: pointer.getBoundingClientRect().top < sceneRect.bottom,
				fullyVisible: previewRect.left >= bannerRect.left - 1
					&& previewRect.right <= bannerRect.right + 1
					&& previewRect.top >= bannerRect.top - 1
					&& previewRect.bottom <= bannerRect.bottom + 1
			};
		});
		expect(previewGeometry.centerDeltaX, 'event preview should dwell at the horizontal center').toBeLessThanOrEqual(2);
		expect(previewGeometry.centerOffsetY, 'event preview center drift should remain subtle').toBeLessThanOrEqual(ACTIONABLE_PREVIEW_CENTER_MAX_OFFSET_Y);
		expect(previewGeometry.centerOffsetY, 'event preview center drift should remain subtle').toBeGreaterThanOrEqual(ACTIONABLE_PREVIEW_CENTER_MIN_OFFSET_Y);
		expect(previewGeometry.fullyVisible, 'event preview should not be clipped during its center dwell').toBe(true);
		expect(previewGeometry.pointerInsideScene, 'pointer should move into the scene before clicking the preview').toBe(true);

		await waitForActionableStage(page, 'luma-cta');
		state = await actionableStageState(page);
		expect(state.stageCount, 'only the active Luma CTA stage should be mounted after transition settle').toBe(1);
		expect(state.hasUserMessage).toBe(false);
		expect(state.hasAssistantMessage).toBe(false);
		expect(state.hasPreview).toBe(false);
		expect(state.hasCtaCard, 'the old custom CTA card must not render').toBe(false);
		expect(state.hasButton).toBe(true);
		expect(state.buttonText).toBe('Open on Luma');
		expect(state.buttonBackground).toBe('rgb(255, 85, 59)');
		await expect(page.getByTestId('landing-actionable-pointer')).toBeVisible({ timeout: ACTIONABLE_INTERACTION_TIMEOUT_MS });
		state = await actionableStageState(page);
		expect(state.hasPointer).toBe(true);
		await expect.poll(
			async () => page.getByTestId('landing-actionable-event-demo').getAttribute('data-interaction-state'),
			{ timeout: ACTIONABLE_INTERACTION_TIMEOUT_MS }
		).toBe('cta-clicked');
		await expect(page.getByTestId('landing-actionable-luma-button')).toHaveAttribute('data-demo-pressed', 'true');
		await expect(page.getByTestId('landing-actionable-event-fullscreen')).toHaveCount(0);
		await expect(page.getByTestId('landing-actionable-event-map')).toHaveCount(0);
		await expect(page.getByTestId('guest-intro-video-shell')).toHaveCount(0);

		const metrics = await page.evaluate(() => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
			const scene = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-scene"]');
			const ctaButton = document.querySelector<HTMLElement>('[data-testid="landing-actionable-luma-button"]');
			if (!banner || !demo || !scene || !ctaButton) {
				throw new Error('Actionable slide elements missing');
			}

			const bannerRect = banner.getBoundingClientRect();
			const demoRect = demo.getBoundingClientRect();
			return {
				bannerHeight: bannerRect.height,
				demoWidth: demoRect.width,
				demoHeight: demoRect.height,
				demoLeftGap: demoRect.left - bannerRect.left,
				demoRightGap: bannerRect.right - demoRect.right,
				sceneAnimation: getComputedStyle(scene).animationName,
				activeStage: demo.dataset.activeStage,
				buttonText: ctaButton.textContent?.trim() || ''
			};
		});

		expect(metrics.bannerHeight).toBeGreaterThanOrEqual(220);
		expect(metrics.demoWidth).toBeGreaterThanOrEqual(360);
		expect(metrics.demoHeight).toBeLessThanOrEqual(metrics.bannerHeight);
		expect(metrics.demoLeftGap).toBeGreaterThanOrEqual(40);
		expect(metrics.demoRightGap).toBeGreaterThanOrEqual(40);
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable');
		expect(metrics.sceneAnimation).toBe('none');
		expect(metrics.activeStage).toBe('luma-cta');
		expect(metrics.buttonText).toBe('Open on Luma');

		await expect(page.getByTestId('landing-actionable-event-demo')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
		await page.waitForTimeout(1200);
		await expect(page.getByTestId('landing-actionable-user-message')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.coordinated-story-progress,landing-onboarding.privacy-mates-platform-stories
	test('collapsed guest inspirations show a moving heading before a centered animation', async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		const viewports = [
			{ width: 393, height: 852 },
			{ width: 600, height: 900 },
			{ width: 731, height: 960 },
			{ width: 1024, height: 900 },
			{ width: 1280, height: 720 },
			{ width: 1280, height: 900 }
		];

		for (const viewport of viewports) {
			await page.setViewportSize(viewport);
			await page.goto(getE2EDebugUrl(`/?collapsed-guest-layout=${viewport.width}`), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');
			await waitForLandingIntroExamples(page);
			await skipExpandedLandingIntro(page);
			await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
			await expect(page.getByTestId('guest-feature-inline-icon')).toHaveCount(0);
			await expect(page.getByTestId('landing-actionable-event-demo')).toHaveCount(0);
			await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-motion-phase', 'visible');
			await expect(page.getByTestId('landing-guest-heading-motion')).toHaveCSS('animation-name', /landingHeadingCenterDrift$/);
			await expect(page.getByTestId('landing-guest-heading-motion')).toHaveCSS('animation-iteration-count', 'infinite');
			const headingStartY = await page.getByTestId('landing-guest-heading-motion').evaluate((heading: HTMLElement) => Number.parseFloat(getComputedStyle(heading).translate.split(' ')[1] || '0'));
			await page.waitForTimeout(420);
			const headingEndY = await page.getByTestId('landing-guest-heading-motion').evaluate((heading: HTMLElement) => Number.parseFloat(getComputedStyle(heading).translate.split(' ')[1] || '0'));
			expect(Math.abs(headingEndY - headingStartY), `${viewport.width}px: visible heading should keep moving`).toBeGreaterThan(0.25);
			await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', { timeout: 4000 });
			await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable');
			await waitForActionableStage(page, 'user-request');

			const metrics = await page.evaluate(() => {
				const area = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-area"]');
				const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
				const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
				if (!area || !banner || !demo) throw new Error('Collapsed guest inspiration elements missing');
				const areaRect = area.getBoundingClientRect();
				const bannerRect = banner.getBoundingClientRect();
				const demoRect = demo.getBoundingClientRect();
				return {
					areaHeight: areaRect.height,
					bannerWidth: bannerRect.width,
					bannerHeight: bannerRect.height,
					demoCenterDeltaX: Math.abs((demoRect.left + demoRect.width / 2) - (bannerRect.left + bannerRect.width / 2)),
					demoOverflowY: Math.max(0, bannerRect.top - demoRect.top, demoRect.bottom - bannerRect.bottom)
				};
			});
			const expectedHeight = Math.max(
				viewport.width <= 730 ? DAILY_INSPIRATION_REFERENCE_HEIGHT : DAILY_INSPIRATION_DESKTOP_MIN_HEIGHT,
				Math.min(
					DAILY_INSPIRATION_MAX_HEIGHT,
					metrics.bannerWidth * DAILY_INSPIRATION_REFERENCE_HEIGHT / DAILY_INSPIRATION_REFERENCE_WIDTH,
					viewport.height * DAILY_INSPIRATION_MAX_VIEWPORT_HEIGHT_RATIO
				)
			);

			expect(metrics.bannerHeight, `${viewport.width}px: banner should preserve the mobile aspect ratio until capped`).toBeCloseTo(expectedHeight, 0);
			expect(metrics.areaHeight, `${viewport.width}px: reserved area should match the banner`).toBeCloseTo(metrics.bannerHeight, 0);
			expect(metrics.demoCenterDeltaX, `${viewport.width}px: animation should be centered`).toBeLessThanOrEqual(3);
			expect(metrics.demoOverflowY, `${viewport.width}px: animation should stay visually attached to the banner`).toBeLessThanOrEqual(ACTIONABLE_DEMO_MAX_BANNER_OVERFLOW_PX);
		}
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.actionable-demo-faithful,landing-onboarding.coordinated-story-progress,landing-onboarding.manual-navigation
	test('mobile actionable slide moves large copy out before showing readable animation', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/?landing-mobile-actionable'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await skipExpandedLandingIntro(page);
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });

		const initialActionable = await mobileActionableSlideState(page);
		expect(initialActionable.bannerHeight, 'regular mobile guest banner should be 20px taller').toBeGreaterThanOrEqual(190);
		expect(initialActionable.headingCount).toBe(1);
		expect(initialActionable.headlineFontSize, 'mobile headline should use display type before the demo appears').toBeGreaterThanOrEqual(32);
		expect(initialActionable.iconCount, 'coordinated story headings must not include category icons').toBe(0);
		expect(initialActionable.demoCount, 'demo must not be mounted during the heading phase').toBe(0);
		expect(initialActionable.headlineLeftGap, 'large mobile headline should remain inside the banner content bounds').toBeLessThanOrEqual(MOBILE_ACTIONABLE_HEADLINE_MAX_LEFT_GAP);
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveAttribute('data-motion-phase', 'visible');
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveCSS('animation-name', /landingHeadingCenterDrift$/);
		await expect(page.getByTestId('landing-guest-heading-motion')).toHaveCSS('animation-iteration-count', 'infinite');
		const headingStartY = await page.getByTestId('landing-guest-heading-motion').evaluate((heading: HTMLElement) => Number.parseFloat(getComputedStyle(heading).translate.split(' ')[1] || '0'));
		await page.waitForTimeout(420);
		const headingEndY = await page.getByTestId('landing-guest-heading-motion').evaluate((heading: HTMLElement) => Number.parseFloat(getComputedStyle(heading).translate.split(' ')[1] || '0'));
		expect(Math.abs(headingEndY - headingStartY), 'heading should continuously slow and accelerate around center').toBeGreaterThan(0.25);

		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-actionable-heading-phase', 'fading-out', {
			timeout: 3000
		});
		const fadingOutActionable = await mobileActionableSlideState(page);
		expect(fadingOutActionable.headlineFontSize, 'heading geometry must remain large throughout fade-out').toBe(initialActionable.headlineFontSize);
		expect(fadingOutActionable.copyTop, 'heading position must not change before fade-out completes').toBeCloseTo(initialActionable.copyTop, 0);
		await expect.poll(
			async () => page.getByTestId('guest-intro-copy').evaluate((copy: HTMLElement) => Number.parseFloat(getComputedStyle(copy).opacity)),
			{ timeout: 3000 }
		).toBeLessThanOrEqual(0.1);
		await expect(page.getByTestId('landing-actionable-event-demo')).toHaveCount(0);
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', { timeout: 1500 });
		await expect(page.getByTestId('guest-intro-copy')).toHaveCount(1);
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable');
		await expect(page.getByTestId('landing-actionable-event-demo')).toHaveAttribute('data-playing', 'true');

		await waitForActionableStage(page, 'user-request');
		await page.waitForTimeout(700);
		const userMessageGeometry = await page.evaluate(() => {
			const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
			const row = document.querySelector<HTMLElement>('[data-testid="landing-actionable-user-row"]');
			const bubble = document.querySelector<HTMLElement>('[data-testid="landing-actionable-user-message"]');
			if (!demo || !row || !bubble) throw new Error('Mobile Actionable user message geometry missing');
			return {
				rowLayoutWidth: row.offsetWidth,
				demoLayoutWidth: demo.clientWidth,
				fontSize: Number.parseFloat(getComputedStyle(bubble).fontSize)
			};
		});
		expect(userMessageGeometry.rowLayoutWidth, 'mobile user message row should remain slightly wider than the demo column').toBeGreaterThanOrEqual(userMessageGeometry.demoLayoutWidth + 8);
		expect(userMessageGeometry.fontSize, 'mobile user message should use the enlarged type scale').toBeGreaterThanOrEqual(13);

		await waitForActionableStage(page, 'assistant-response');
		await page.waitForTimeout(700);
		const demoActionable = await mobileActionableSlideState(page);
		const assistantMessageGeometry = await page.evaluate(() => {
			const demo = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-demo"]');
			const row = document.querySelector<HTMLElement>('[data-testid="landing-actionable-assistant-row"]');
			const bubble = document.querySelector<HTMLElement>('[data-testid="landing-actionable-assistant-message"]');
			if (!demo || !row || !bubble) throw new Error('Mobile Actionable assistant message geometry missing');
			return {
				rowLayoutWidth: row.offsetWidth,
				demoLayoutWidth: demo.clientWidth,
				fontSize: Number.parseFloat(getComputedStyle(bubble).fontSize)
			};
		});
		expect(assistantMessageGeometry.rowLayoutWidth, 'mobile assistant message row should remain slightly wider than the demo column').toBeGreaterThanOrEqual(assistantMessageGeometry.demoLayoutWidth + 8);
		expect(assistantMessageGeometry.fontSize, 'mobile assistant message should use the enlarged type scale').toBeGreaterThanOrEqual(13);
		expect(demoActionable.headingCount, 'the reduced heading should stay mounted while the demo plays').toBe(1);
		expect(demoActionable.iconCount).toBe(0);
		expect(demoActionable.demoOpacity, 'demo should be visible after the heading exits').toBeGreaterThanOrEqual(0.85);
		const compactDemoOverflowY = Math.max(0, demoActionable.demoBottom - demoActionable.bannerBottom);
		expect(compactDemoOverflowY, 'demo should stay visually attached to the banner after compacting').toBeLessThanOrEqual(ACTIONABLE_DEMO_MAX_BANNER_OVERFLOW_PX);
		expect(demoActionable.demoHeight, 'demo should keep useful vertical space').toBeGreaterThanOrEqual(80);
		expect(demoActionable.reportButtonTop, 'report issue button should sit below the mobile banner, not behind it').toBeGreaterThanOrEqual(demoActionable.bannerBottom + 4);
		expect(demoActionable.demoBackground, 'actionable demo should be transparent inside the gradient banner').toBe('rgba(0, 0, 0, 0)');
		expect(demoActionable.demoBorderWidth, 'actionable demo should not render a dark boxed border').toBe('0px');
		expect(demoActionable.demoBoxShadow, 'actionable demo should not render a boxed shadow').toBe('none');
		expect(demoActionable.demoContentCenterDeltaX, 'actionable demo content should be horizontally centered').toBeLessThanOrEqual(MOBILE_ACTIONABLE_CONTENT_CENTER_MAX_DELTA_X);
		expect(demoActionable.demoContentCenterDeltaY, 'actionable demo content should be vertically centered').toBeLessThanOrEqual(MOBILE_ACTIONABLE_CONTENT_CENTER_MAX_DELTA_Y);

		await waitForActionableStage(page, 'event-preview');
		await expect.poll(
			async () => page.getByTestId('landing-actionable-event-demo').getAttribute('data-interaction-state'),
			{ timeout: ACTIONABLE_INTERACTION_TIMEOUT_MS }
		).toBe('preview-clicked');
		const mobilePreviewGeometry = await page.evaluate(() => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const preview = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-preview"]');
			const scene = document.querySelector<HTMLElement>('[data-testid="landing-actionable-event-scene"]');
			const infoBar = preview?.querySelector<HTMLElement>('[data-testid="embed-basic-infos-bar"]');
			if (!banner || !preview || !scene || !infoBar) throw new Error('Mobile Actionable preview geometry elements missing');
			const bannerRect = banner.getBoundingClientRect();
			const previewRect = preview.getBoundingClientRect();
			const sceneRect = scene.getBoundingClientRect();
			const infoBarRect = infoBar.getBoundingClientRect();
			return {
				centerDeltaX: Math.abs((previewRect.left + previewRect.width / 2) - (sceneRect.left + sceneRect.width / 2)),
				infoBarHeight: infoBarRect.height,
				infoBarVisible: infoBarRect.top >= previewRect.top && infoBarRect.bottom <= previewRect.bottom + 1,
				fullyVisible: previewRect.left >= bannerRect.left - 1
					&& previewRect.right <= bannerRect.right + 1
					&& previewRect.top >= bannerRect.top - 1
					&& previewRect.bottom <= bannerRect.bottom + 1
			};
		});
		expect(mobilePreviewGeometry.centerDeltaX, 'mobile event preview should remain horizontally centered').toBeLessThanOrEqual(2);
		expect(mobilePreviewGeometry.infoBarHeight, 'mobile event preview should render its complete bottom info bar').toBeGreaterThanOrEqual(28);
		expect(mobilePreviewGeometry.infoBarVisible, 'mobile event preview bottom info bar should remain inside the rounded card').toBe(true);
		expect(mobilePreviewGeometry.fullyVisible, 'mobile event preview should be fully visible during the demo-only phase').toBe(true);

		await page.evaluate((fadeSettleMs: number) => {
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const content = document.querySelector<HTMLElement>('[data-testid="guest-slide-content"]');
			if (!banner || !content) throw new Error('Guest slide transition elements missing');
			const transitionWindow = window as typeof window & {
				__guestSlideTransitionSamples?: Array<{ phase: string; inspirationId: string; opacity: number }>;
			};
			transitionWindow.__guestSlideTransitionSamples = [];
			const observer = new MutationObserver(() => {
				transitionWindow.__guestSlideTransitionSamples?.push({
					phase: banner.dataset.guestSlidePhase ?? '',
					inspirationId: banner.dataset.currentInspirationId ?? '',
					opacity: Number.parseFloat(getComputedStyle(content).opacity)
				});
			});
			observer.observe(banner, { attributes: true, childList: true, subtree: true });
			window.setTimeout(() => observer.disconnect(), fadeSettleMs * 2);
		}, MOBILE_SLIDE_FADE_SETTLE_MS);
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-guest-slide-phase', 'idle');
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
		await expect.poll(
			async () => page.getByTestId('guest-slide-content').evaluate((content: HTMLElement) => Number.parseFloat(getComputedStyle(content).opacity)),
			{ timeout: MOBILE_SLIDE_FADE_SETTLE_MS }
		).toBeGreaterThanOrEqual(0.95);
		const transitionSamples = await page.evaluate(() => (
			(window as typeof window & {
				__guestSlideTransitionSamples?: Array<{ phase: string; inspirationId: string; opacity: number }>;
			}).__guestSlideTransitionSamples ?? []
		));
		expect(
			transitionSamples.every((sample) => sample.opacity >= 0.95),
			'guest slide navigation must not show a blank or faint transition frame'
		).toBe(true);

		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-guest-slide-phase', 'idle');
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-actionable-events');
		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-landing-intro-phase', 'expanded');
		await expect(page.getByTestId('landing-intro-headline')).toHaveText(LANDING_INTRO_HEADLINE_TEXT);
		await expect(page.getByTestId('guest-intro-copy')).toHaveCount(0);
		await expect(page.getByTestId('daily-inspiration-phrase')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-sequence
	test('regular guest landing exposes workspace prompt, CTA input links, compact cards, and all examples', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.addInitScript(() => {
			class FakeMediaRecorder extends EventTarget {
				static isTypeSupported() { return true; }
				state = 'inactive';
				mimeType = 'audio/webm';
				ondataavailable: ((event: Event) => void) | null = null;
				onstop: (() => void) | null = null;
				onerror: ((event: Event) => void) | null = null;
				start() {
					this.state = 'recording';
				}
				stop() {
					this.state = 'inactive';
					this.onstop?.();
					this.dispatchEvent(new Event('stop'));
				}
			}
			Object.defineProperty(window, 'MediaRecorder', {
				configurable: true,
				value: FakeMediaRecorder
			});
			Object.defineProperty(navigator, 'mediaDevices', {
				configurable: true,
				value: {
					getUserMedia: async () => new MediaStream()
				}
			});
		});

		await page.goto(getE2EDebugUrl('/?landing-guest-refresh'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('guest-workspace-icon')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('welcome-content')).toContainText('Click or swipe, to explore real chats:');
		await expect(page.getByTestId('welcome-content')).not.toContainText('Hey there');
		await expect(page.getByTestId('guest-input-context-link')).toBeVisible();
		await page.getByTestId('message-editor').click();
		await expect(page.getByTestId('guest-input-context-link')).not.toBeVisible({ timeout: 1000 });
		await page.evaluate(() => {
			const activeElement = document.activeElement;
			if (activeElement instanceof HTMLElement) activeElement.blur();
		});
		await expect(page.getByTestId('guest-input-context-link')).toBeVisible({ timeout: 1000 });
		await expect(page.getByTestId('guest-cta-mic-button')).toBeVisible();
		const visualState = await page.evaluate(() => {
			const workspaceIcon = document.querySelector<HTMLElement>('[data-testid="guest-workspace-icon"]');
			const messageField = document.querySelector<HTMLElement>('[data-testid="message-field"]');
			const micButton = document.querySelector<HTMLElement>('[data-testid="guest-cta-mic-button"]');
			if (!workspaceIcon || !messageField || !micButton) throw new Error('Guest landing visual elements missing');
			const iconStyle = getComputedStyle(workspaceIcon);
			const fieldStyle = getComputedStyle(messageField);
			const micStyle = getComputedStyle(micButton);
			const iconWebkitStyle = iconStyle as CSSStyleDeclaration & { webkitMaskImage?: string };
			const micRect = micButton.getBoundingClientRect();
			return {
				workspaceSurface: workspaceIcon.dataset.surface,
				workspaceMask: iconStyle.maskImage || iconWebkitStyle.webkitMaskImage,
				workspaceBackground: iconStyle.backgroundColor,
				workspaceBoxShadow: iconStyle.boxShadow,
				workspaceBorderRadius: iconStyle.borderRadius,
				fieldBackgroundImage: fieldStyle.backgroundImage,
				fieldBorderRadius: fieldStyle.borderRadius,
				micWidth: micRect.width,
				micHeight: micRect.height,
				micBorderRadius: micStyle.borderRadius,
				micBoxShadow: micStyle.boxShadow
			};
		});
		expect(visualState.workspaceSurface).toBe('chats');
		expect(visualState.workspaceMask).toContain('image/svg+xml');
		expect(visualState.workspaceBackground).not.toBe('rgba(0, 0, 0, 0)');
		expect(visualState.workspaceBoxShadow).toBe('none');
		expect(visualState.workspaceBorderRadius).toBe('0px');
		expect(visualState.fieldBackgroundImage).toBe('none');
		expect(Number.parseFloat(visualState.fieldBorderRadius)).toBeGreaterThanOrEqual(24);
		expect(visualState.micWidth).toBeLessThanOrEqual(30);
		expect(visualState.micHeight).toBeLessThanOrEqual(30);
		expect(visualState.micBorderRadius).toBe('0px');
		expect(visualState.micBoxShadow).toBe('none');

		await page.getByTestId('guest-cta-mic-button').click();
		await expect(page.getByTestId('record-overlay')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('record-finish-button')).toContainText('Finish');
		await expect(page.getByTestId('record-cancel-button')).toContainText('Cancel');
		const finishButtonStyle = await page.getByTestId('record-finish-button').evaluate((element: HTMLElement) => {
			const elementStyle = getComputedStyle(element);
			const resolveBackground = (value: string): string => {
				const colorProbe = document.createElement('span');
				colorProbe.style.backgroundColor = value.trim();
				document.body.appendChild(colorProbe);
				const background = getComputedStyle(colorProbe).backgroundColor;
				colorProbe.remove();
				return background;
			};
			const parseRgb = (value: string): [number, number, number] | null => {
				const match = value.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
				return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
			};
			const channelDistance = (left: string, right: string): number => {
				const leftRgb = parseRgb(left);
				const rightRgb = parseRgb(right);
				if (!leftRgb || !rightRgb) return Number.POSITIVE_INFINITY;
				return Math.max(
					Math.abs(leftRgb[0] - rightRgb[0]),
					Math.abs(leftRgb[1] - rightRgb[1]),
					Math.abs(leftRgb[2] - rightRgb[2])
				);
			};
			const primaryBackgrounds = [
				resolveBackground(elementStyle.getPropertyValue('--color-button-primary')),
				resolveBackground(elementStyle.getPropertyValue('--color-button-primary-hover')),
				resolveBackground(elementStyle.getPropertyValue('--color-button-primary-pressed'))
			];

			return {
				backgroundColor: elementStyle.backgroundColor,
				color: elementStyle.color,
				primaryDistance: Math.min(...primaryBackgrounds.map((background) => channelDistance(elementStyle.backgroundColor, background)))
			};
		});
		expect(finishButtonStyle.primaryDistance).toBeLessThanOrEqual(PRIMARY_BUTTON_COLOR_TOLERANCE);
		expect(finishButtonStyle.color).toBe('rgb(255, 255, 255)');
		await expect(page.getByTestId('cancel-hint')).toHaveCount(0);
		await expect(page.getByTestId('release-text')).toContainText('Recording');
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('record-overlay')).toHaveCount(0, { timeout: 5000 });

		const guestPlaceholder = await getGuestComposerPlaceholder(page);
		expect(guestPlaceholder).toMatch(/Click here to (test for free|ask anything)/);
		await expect(page.getByTestId('resume-chat-card').first()).toBeVisible();
		await expect(page.getByTestId('resume-chat-large-card')).toHaveCount(0);

		const bannerState = await page.getByTestId('daily-inspiration-banner').evaluate((element: HTMLElement) => ({
			mountedIndexes: element.dataset.mountedSlideIndexes,
			visibleIds: element.dataset.visibleInspirationIds,
			progressHeight: document.querySelector<HTMLElement>('[data-testid="daily-inspiration-carousel-progress"]')?.getBoundingClientRect().height ?? 0
		}));
		expect(bannerState.mountedIndexes).toBe('0,1,2');
		expect(bannerState.progressHeight).toBeGreaterThanOrEqual(4);
		expect(bannerState.visibleIds).toBe(
			'openmates-intro,openmates-actionable-events,openmates-privacy-safety,openmates-mates-focus,openmates-provider-cross-platform,openmates-signup-cta'
		);
		for (const oldId of [
			'pii-detection',
			'relevant-memories',
			'trusted-quotes',
			'events-search',
			'learning-mode',
			'audio-messages',
			'chat-file-downloads',
			'provider-independent'
		]) {
			expect(bannerState.visibleIds).not.toContain(oldId);
		}

		await page.getByTestId('guest-show-all-examples').click();
		await expect(page.getByTestId('daily-inspiration-area')).toBeHidden();
		const allExamplesView = page.getByTestId('guest-all-examples-view');
		await expect(allExamplesView).toBeVisible({ timeout: 5000 });
		await expect(allExamplesView.getByTestId('resume-chat-large-card').first()).toBeVisible();
		await expect(page.getByTestId('message-input-wrapper')).toBeVisible();
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('guest composer placeholder resolves after async locale load', async ({ page }: { page: any }) => {
		test.setTimeout(30000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.addInitScript(() => {
			localStorage.setItem('preferredLanguage', 'de');
		});

		await page.goto(getE2EDebugUrl('/?landing-guest-placeholder-locale'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('message-field')).toBeVisible({ timeout: 10000 });
		await expect.poll(() => getGuestComposerPlaceholder(page), { timeout: 6000 }).toMatch(
			/Klicke hier, um (es kostenlos zu testen|alles zu fragen)/
		);
		const guestPlaceholder = await getGuestComposerPlaceholder(page);
		expect(guestPlaceholder).not.toBe('Loading...');
		expect(guestPlaceholder).not.toContain('[T:');
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.guest-sequence,landing-onboarding.manual-navigation,landing-onboarding.signup-cta
	test('final signup CTA opens the shared signup interface without a signup hash', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.emulateMedia({ reducedMotion: 'no-preference' });

		await page.goto(getE2EDebugUrl('/?landing-signup-cta'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await skipExpandedLandingIntro(page);

		for (let index = 0; index < 4; index += 1) {
			await page.getByTestId('daily-inspiration-next').click();
		}

		await expect(page.getByTestId('landing-signup-cta')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('landing-signup-cta')).toHaveAttribute('data-stage', 'benefits');
		await expect(page.getByTestId('landing-signup-benefits')).toBeVisible();
		await expect(page.getByTestId('landing-signup-benefits')).toContainText('No ads');
		await expect(page.getByTestId('landing-signup-cta-button')).toBeHidden();
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
		const headerGithubLink = page.getByRole('link', { name: 'Open OpenMates GitHub repository' });
		await expect(headerGithubLink).toBeVisible();
		const headerGithubBeforeCta = await headerGithubLink.boundingBox();
		expect(headerGithubBeforeCta).not.toBeNull();
		await expect(page.getByTestId('daily-inspiration-banner')).not.toHaveAttribute('role');
		await expect(page.getByTestId('daily-inspiration-banner')).not.toHaveAttribute('tabindex');
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveCSS('cursor', 'default');
		const benefitRects = await page.getByTestId('landing-signup-benefit').evaluateAll((items: HTMLElement[]) => (
			items.map((item) => item.getBoundingClientRect())
		));
		const benefitsSurface = await page.getByTestId('landing-signup-benefits').evaluate((element: HTMLElement) => {
			const stageStyle = getComputedStyle(element.parentElement as HTMLElement);
			return {
				backgroundColor: stageStyle.backgroundColor,
				boxShadow: stageStyle.boxShadow
			};
		});
		expect(benefitRects).toHaveLength(4);
		expect(Math.abs(benefitRects[0].top - benefitRects[1].top)).toBeLessThanOrEqual(2);
		expect(Math.abs(benefitRects[2].top - benefitRects[3].top)).toBeLessThanOrEqual(2);
		expect(benefitRects[1].left - benefitRects[0].left).toBeGreaterThan(20);
		expect(benefitsSurface.backgroundColor).toBe('rgba(0, 0, 0, 0)');
		expect(benefitsSurface.boxShadow).toBe('none');
		await expect(page.getByTestId('daily-inspiration-next')).toHaveCount(0);
		await expect(page.getByTestId('daily-inspiration-previous')).toBeVisible();

		await expect(page.getByTestId('landing-signup-cta')).toHaveAttribute('data-stage', 'cta', { timeout: 6000 });
		await expect(page.getByTestId('landing-signup-cta')).toContainText('Start using OpenMates');
		await expect(page.getByTestId('landing-signup-benefits')).toBeHidden();
		await expect(page.getByTestId('landing-signup-cta-button')).toBeVisible();
		await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();
		await expect(headerGithubLink).toBeVisible();
		await expect.poll(async () => {
			const box = await headerGithubLink.boundingBox();
			return box?.x ?? 0;
		}, { timeout: 2000 }).toBeGreaterThan(headerGithubBeforeCta!.x + 40);
		const signupCtaPresentation = await page.getByTestId('landing-signup-cta-button').evaluate((element: HTMLElement) => {
			const style = getComputedStyle(element);
			const rect = element.getBoundingClientRect();
			return {
				height: rect.height,
				marginTop: style.marginTop,
				animationName: style.animationName,
				animationDuration: style.animationDuration,
				animationIterationCount: style.animationIterationCount
			};
		});
		expect(signupCtaPresentation.height).toBeGreaterThanOrEqual(56);
		expect(signupCtaPresentation.marginTop).toBe('10px');
		expect(signupCtaPresentation.animationName).toContain('landingSignupCtaPulse');
		expect(signupCtaPresentation.animationDuration).toBe('4.8s');
		expect(signupCtaPresentation.animationIterationCount).toBe('infinite');
		await expect(page.getByTestId('daily-inspiration-banner')).not.toHaveAttribute('role');
		await expect(page.getByTestId('daily-inspiration-banner')).not.toHaveAttribute('tabindex');

		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('landing-signup-cta')).toHaveCount(0);
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('landing-signup-cta')).toHaveAttribute('data-stage', 'benefits');
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
		await expect(page.getByTestId('landing-signup-cta')).toHaveAttribute('data-stage', 'cta', { timeout: 6000 });
		await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();

		await page.evaluate(() => {
			const trackedWindow = window as Window & { __landingSignupEventCount?: number };
			trackedWindow.__landingSignupEventCount = 0;
			window.addEventListener('openSignupInterface', () => {
				trackedWindow.__landingSignupEventCount = (trackedWindow.__landingSignupEventCount ?? 0) + 1;
			});
		});

		await page.getByTestId('landing-signup-cta-button').click({ force: true });
		await expect.poll(async () => page.evaluate(() => {
			const trackedWindow = window as Window & { __landingSignupEventCount?: number };
			return trackedWindow.__landingSignupEventCount ?? 0;
		}), { timeout: 1000 }).toBe(1);
		await expect(page.getByTestId('login-wrapper')).toBeVisible({ timeout: 5000 });
		await expect.poll(async () => page.evaluate(() => window.location.hash), { timeout: 1000 }).not.toContain('#signup/');

		await page.getByTestId('login-wrapper').getByRole('button', { name: 'Demo', exact: true }).click();
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('guest example chat follow-up input matches the adjacent new-chat CTA height', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/?landing-guest-refresh'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await waitForLandingIntroExamples(page);
		await skipExpandedLandingIntro(page);

		await page.getByTestId('resume-chat-card').filter({ hasText: 'AI Workshops' }).first().click();
		await expect(page.getByTestId('new-chat-button')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('message-field')).toBeVisible({ timeout: 10000 });

		await expect.poll(async () => page.evaluate(() => {
			const messageField = document.querySelector<HTMLElement>('[data-testid="message-field"]');
			const newChatButton = document.querySelector<HTMLElement>('[data-testid="new-chat-button"]');
			if (!messageField || !newChatButton) throw new Error('Example chat composer elements missing');
			return Math.abs(messageField.getBoundingClientRect().height - newChatButton.getBoundingClientRect().height);
		}), { timeout: 3000 }).toBeLessThanOrEqual(1);
	});
});
