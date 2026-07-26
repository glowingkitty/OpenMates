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

async function landingIntroOverlayMetrics(page: any): Promise<{
	phase: string | null;
	activeHeight: number;
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
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const messageInput = document.querySelector<HTMLElement>('[data-testid="message-input-wrapper"]');
		const welcomeContent = document.querySelector<HTMLElement>('[data-testid="welcome-content"]');
		const introContent = document.querySelector<HTMLElement>('[data-testid="landing-intro-expanded"]');
		if (!active || !banner || !messageInput || !welcomeContent) {
			throw new Error('Landing intro overlay elements missing');
		}

		const activeRect = active.getBoundingClientRect();
		const bannerRect = banner.getBoundingClientRect();
		return {
			phase: banner.getAttribute('data-landing-intro-phase'),
			activeHeight: activeRect.height,
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

test.describe('Landing page onboarding refresh', () => {
	test('expanded intro fits all target device viewports', async ({ page }: { page: any }) => {
		test.setTimeout(120000);

		for (const viewport of LANDING_INTRO_VIEWPORTS) {
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			await page.goto(getE2EDebugUrl(`/?landing-layout=${viewport.name}`), { waitUntil: 'domcontentloaded' });
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
		}
	});

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
		expect(expanded.messageInputOpacity, 'message input is transparent while covered').toBeLessThanOrEqual(0.05);
		expect(expanded.welcomeContentOpacity, 'welcome content is transparent while covered').toBeLessThanOrEqual(0.05);

		await page.getByTestId('daily-inspiration-next').click();
		await expect.poll(async () => {
			const phase = (await landingIntroOverlayMetrics(page)).phase;
			return phase === 'fading-out' || phase === 'collapsing';
		}, { timeout: 1000 }).toBe(true);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).introContentOpacity ?? 1, { timeout: 1500 }).toBeLessThan(0.2);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).phase, { timeout: 2000 }).toBe('collapsing');
		await expect(page.getByTestId('landing-actionable-event-demo')).toHaveCount(0);
		await expect.poll(async () => (await landingIntroOverlayMetrics(page)).messageInputOpacity, { timeout: 1500 }).toBeGreaterThan(0.2);
		const collapsing = await landingIntroOverlayMetrics(page);
		expect(collapsing.messageInputOpacity, 'message input fades in while intro shrinks').toBeGreaterThan(0.2);
		expect(collapsing.welcomeContentOpacity, 'welcome content fades in while intro shrinks').toBeGreaterThan(0.2);

		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		const regular = await landingIntroOverlayMetrics(page);
		expect(regular.phase).toBe('regular');
		expect(regular.bannerHeight, 'regular daily inspiration is smaller than the active chat').toBeLessThan(regular.activeHeight * 0.55);
		expect(regular.messageInputOpacity, 'message input is visible after collapse').toBeGreaterThanOrEqual(0.95);
		expect(regular.welcomeContentOpacity, 'welcome content is visible after collapse').toBeGreaterThanOrEqual(0.95);

		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 5000 });
		await waitForExpandedIntroToCoverActiveChat(page);
		const restored = await landingIntroOverlayMetrics(page);
		expect(restored.bannerActiveBottomDelta, 'returning to slide one expands over active chat bottom').toBeLessThanOrEqual(2);
		expect(restored.messageInputOpacity, 'message input fades out when slide one expands again').toBeLessThanOrEqual(0.05);
		expect(restored.welcomeContentOpacity, 'welcome content fades out when slide one expands again').toBeLessThanOrEqual(0.05);
	});

	test('settings panel keeps active chat fixed inside the viewport', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1920, height: 1080 });

		await page.goto(getE2EDebugUrl('/?settings-active-chat-layout'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });

		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });

		const activeChatLayout = await page.getByTestId('active-chat-container').evaluate((element: HTMLElement) => {
			const rect = element.getBoundingClientRect();
			return {
				bottom: rect.bottom,
				overflowY: getComputedStyle(element).overflowY,
				viewportHeight: window.innerHeight
			};
		});
		expect(activeChatLayout.overflowY, 'active chat itself must not become vertically scrollable').toBe('hidden');
		expect(activeChatLayout.bottom, 'settings panel must not push active chat below the viewport').toBeLessThanOrEqual(
			activeChatLayout.viewportHeight - 1
		);
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

		expect(metrics.bannerHeight).toBeGreaterThanOrEqual(220);
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
			const style = getComputedStyle(element);
			return {
				backgroundColor: style.backgroundColor,
				buttonPrimary: getComputedStyle(document.documentElement).getPropertyValue('--color-button-primary').trim(),
				color: style.color
			};
		});
		expect(finishButtonStyle.backgroundColor).toBe(finishButtonStyle.buttonPrimary);
		expect(finishButtonStyle.color).toBe('rgb(255, 255, 255)');
		await expect(page.getByTestId('cancel-hint')).toHaveCount(0);
		await expect(page.getByTestId('release-text')).toContainText('Recording');
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('record-overlay')).toHaveCount(0, { timeout: 5000 });

		const guestPlaceholder = await page.getByTestId('message-editor').evaluate((element: HTMLElement) => {
			const paragraph = element.querySelector<HTMLElement>('.ProseMirror p[data-placeholder]');
			return paragraph?.dataset.placeholder ?? '';
		});
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
			'openmates-intro,openmates-actionable-events,openmates-privacy-safety,openmates-mates-focus,openmates-provider-cross-platform'
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
		await expect(page.getByTestId('daily-inspiration-area')).toHaveCount(0);
		await expect(page.getByTestId('guest-all-examples-view')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('guest-all-example-card').first()).toBeVisible();
		await expect(page.getByTestId('message-input-wrapper')).toBeVisible();
	});

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

		const heights = await page.evaluate(() => {
			const messageField = document.querySelector<HTMLElement>('[data-testid="message-field"]');
			const newChatButton = document.querySelector<HTMLElement>('[data-testid="new-chat-button"]');
			if (!messageField || !newChatButton) throw new Error('Example chat composer elements missing');
			return {
				fieldHeight: messageField.getBoundingClientRect().height,
				buttonHeight: newChatButton.getBoundingClientRect().height
			};
		});

		expect(Math.abs(heights.fieldHeight - heights.buttonHeight)).toBeLessThanOrEqual(1);
	});
});
