/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Guest interest smart-selection E2E coverage.
 *
 * Verifies the logged-out landing contract from
 * docs/specs/landing-page-onboarding-refresh/spec.yml and the legacy
 * docs/specs/guest-interest-smart-selection/spec.yml behavior that still exists
 * after the phase-1 intro is skipped.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const GUEST_TOPIC_PREFERENCES_STORAGE_KEY = 'openmates.guest_interest_tags.v1';
const SELECTED_INTEREST_TAGS = [
	'software_development',
	'privacy',
	'run_code',
	'build_electronics'
];
const LANDING_INTRO_REQUESTS = [
	'Find doctor appointments',
	'Find events',
	'Build a web app',
	'Explain the news'
];
const LANDING_INTRO_HEADLINE_TEXT = 'Simply ask your\nAI team mates';
const LANDING_INTRO_HIGHLIGHTED_APPS = ['health', 'events', 'code', 'news'];
const LANDING_INTRO_REQUEST_APP_IDS = new Map(
	LANDING_INTRO_REQUESTS.map((request, index) => [request, LANDING_INTRO_HIGHLIGHTED_APPS[index]])
);

async function interestTagOrder(page: any): Promise<string[]> {
	return page.getByTestId('guest-interest-rail').locator('button[data-testid^="interest-tag-"]').evaluateAll(
		(nodes: Element[]) => nodes.map((node) => (node.getAttribute('data-testid') || '').replace('interest-tag-', ''))
	);
}

async function visibleSuggestionIds(page: any): Promise<string[]> {
	return page.getByTestId('new-chat-suggestion-card').evaluateAll(
		(nodes: Element[]) => nodes.map((node) => node.getAttribute('data-suggestion-id') || '')
	);
}

function firstContinueChatCard(page: any) {
	return page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').first();
}

async function clickInterestTag(page: any, tagId: string): Promise<void> {
	await page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement, id: string) => {
		const tag = rail.querySelector<HTMLElement>(`[data-testid="interest-tag-${id}"]`);
		if (!tag) throw new Error(`${id} tag not found`);
		const previousScrollBehavior = rail.style.scrollBehavior;
		rail.style.scrollBehavior = 'auto';
		rail.scrollLeft = Math.max(0, tag.offsetLeft - rail.clientWidth / 2 + tag.offsetWidth / 2);
		rail.style.scrollBehavior = previousScrollBehavior;
	}, tagId);
	await page.getByTestId(`interest-tag-${tagId}`).click();
}

async function tagRailMetrics(page: any): Promise<{
	availableTagCount: number;
	selectedTagCount: number;
}> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
		const tags = Array.from(rail.querySelectorAll<HTMLElement>('button[data-testid^="interest-tag-"]'));
		const selectedTagCount = tags.filter((tag) => tag.getAttribute('data-interest-active') === 'true').length;
		return {
			availableTagCount: tags.length - selectedTagCount,
			selectedTagCount
		};
	});
}

async function tagRailSideGaps(page: any): Promise<{ left: number; right: number }> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
		const chatContainer = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
		const railRect = rail.getBoundingClientRect();
		const chatRect = chatContainer?.getBoundingClientRect();
		if (!chatRect) return { left: Number.POSITIVE_INFINITY, right: Number.POSITIVE_INFINITY };
		return {
			left: Math.abs(railRect.left - chatRect.left),
			right: Math.abs(chatRect.right - railRect.right)
		};
	});
}

async function firstAvailableTagCenterDelta(page: any): Promise<number> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
		const firstAvailableTag = rail.querySelector<HTMLElement>('[data-interest-active="false"]');
		if (!firstAvailableTag) return Number.POSITIVE_INFINITY;
		const railRect = rail.getBoundingClientRect();
		const tagRect = firstAvailableTag.getBoundingClientRect();
		return Math.abs((railRect.left + railRect.width / 2) - (tagRect.left + tagRect.width / 2));
	});
}

async function lastTagCenterDeltaAtScrollEnd(page: any): Promise<number> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
		const tags = Array.from(rail.querySelectorAll<HTMLElement>('button[data-testid^="interest-tag-"]'));
		const lastTag = tags[tags.length - 1];
		if (!lastTag) return Number.POSITIVE_INFINITY;
		const previousScrollBehavior = rail.style.scrollBehavior;
		const previousScrollLeft = rail.scrollLeft;
		rail.style.scrollBehavior = 'auto';
		rail.scrollLeft = rail.scrollWidth;
		const railRect = rail.getBoundingClientRect();
		const tagRect = lastTag.getBoundingClientRect();
		const centerDelta = Math.abs((railRect.left + railRect.width / 2) - (tagRect.left + tagRect.width / 2));
		rail.scrollLeft = previousScrollLeft;
		rail.style.scrollBehavior = previousScrollBehavior;
		return centerDelta;
	});
}

async function interestTagsPromptGap(page: any): Promise<number> {
	const promptBox = await page.getByText('What are your interests?').boundingBox();
	const tagsBox = await page.getByTestId('guest-interest-tags').boundingBox();
	if (!promptBox || !tagsBox) return Number.NEGATIVE_INFINITY;
	return tagsBox.y - (promptBox.y + promptBox.height);
}

async function skipExpandedLandingIntro(page: any): Promise<void> {
	await page.getByTestId('daily-inspiration-next').click();
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
}

async function landingIntroState(page: any): Promise<{
	requestLabel: string;
	highlightedAppIds: string[];
}> {
	return page.evaluate(() => ({
		requestLabel: document.querySelector('[data-testid="landing-intro-request"]')?.textContent?.trim() || '',
		highlightedAppIds: Array.from(document.querySelectorAll('[data-testid="landing-intro-app-icon"][data-highlighted="true"]'))
			.map((node) => node.getAttribute('data-app-id') || '')
			.filter(Boolean)
	}));
}

async function landingIntroIpadLandscapeMetrics(page: any): Promise<{
	bannerHeight: number;
	bannerBottomGap: number;
	headlineTopRatio: number;
	headlineText: string;
	headlineFontSize: number;
	headlineRequestGap: number;
	rails: Array<{
		iconCount: number;
		bannerWidth: number;
		oneCycleWidth: number;
		leftGap: number;
		rightGap: number;
		maxGap: number;
		rowBottomGap: number;
	}>;
}> {
	return page.evaluate(() => {
		const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
		const headline = document.querySelector<HTMLElement>('[data-testid="landing-intro-headline"]');
		const request = document.querySelector<HTMLElement>('[data-testid="landing-intro-request"]');
		if (!banner || !headline || !request) throw new Error('landing intro elements not found');

		const bannerRect = banner.getBoundingClientRect();
		const headlineRect = headline.getBoundingClientRect();
		const requestRect = request.getBoundingClientRect();
		const rails = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-rail"]'));

		return {
			bannerHeight: bannerRect.height,
			bannerBottomGap: window.innerHeight - bannerRect.bottom,
			headlineTopRatio: (headlineRect.top - bannerRect.top) / bannerRect.height,
			headlineText: headline.innerText.trim(),
			headlineFontSize: Number.parseFloat(getComputedStyle(headline).fontSize),
			headlineRequestGap: requestRect.top - headlineRect.bottom,
			rails: rails.map((rail) => {
				const row = rail.parentElement as HTMLElement | null;
				if (!row) throw new Error('landing intro rail row not found');
				const rowRect = row.getBoundingClientRect();
				const clippedIconRects = Array.from(rail.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"]'))
					.map((icon) => {
						const rect = icon.getBoundingClientRect();
						return {
							left: Math.max(rect.left, bannerRect.left),
							right: Math.min(rect.right, bannerRect.right)
						};
					})
					.filter((rect) => rect.right > rect.left)
					.sort((a, b) => a.left - b.left);
				let maxGap = 0;
				for (let index = 1; index < clippedIconRects.length; index += 1) {
					maxGap = Math.max(maxGap, clippedIconRects[index].left - clippedIconRects[index - 1].right);
				}
				return {
					iconCount: rail.querySelectorAll('[data-testid="landing-intro-app-icon"]').length,
					bannerWidth: bannerRect.width,
					oneCycleWidth: rail.scrollWidth / 2,
					leftGap: clippedIconRects.length > 0 ? clippedIconRects[0].left - bannerRect.left : Number.POSITIVE_INFINITY,
					rightGap: clippedIconRects.length > 0 ? bannerRect.right - clippedIconRects[clippedIconRects.length - 1].right : Number.POSITIVE_INFINITY,
					maxGap,
					rowBottomGap: bannerRect.bottom - rowRect.bottom
				};
			})
		};
	});
}

test.describe('Guest interest smart selection', () => {
	test('expanded landing intro uses the iPad landscape viewport without rail clipping', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1000, height: 712 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await expect.poll(async () => (await landingIntroState(page)).requestLabel, { timeout: 5000 }).toBeTruthy();
		await expect(page.getByTestId('landing-intro-app-rail')).toHaveCount(2, { timeout: 5000 });

		const metrics = await landingIntroIpadLandscapeMetrics(page);
		expect(metrics.bannerHeight).toBeGreaterThanOrEqual(560);
		expect(metrics.bannerBottomGap).toBeLessThanOrEqual(48);
		expect(metrics.headlineTopRatio).toBeLessThanOrEqual(0.36);
		expect(metrics.headlineText).toBe(LANDING_INTRO_HEADLINE_TEXT);
		expect(metrics.headlineFontSize).toBeGreaterThanOrEqual(44);
		expect(metrics.headlineRequestGap).toBeGreaterThanOrEqual(4);
		expect(metrics.headlineRequestGap).toBeLessThanOrEqual(48);
		for (const rail of metrics.rails) {
			expect(rail.iconCount).toBeGreaterThanOrEqual(64);
			expect(rail.oneCycleWidth).toBeGreaterThanOrEqual(rail.bannerWidth + 320);
			expect(rail.leftGap).toBeLessThanOrEqual(4);
			expect(rail.rightGap).toBeLessThanOrEqual(4);
			expect(rail.maxGap).toBeLessThanOrEqual(72);
			expect(rail.rowBottomGap).toBeGreaterThanOrEqual(8);
		}
	});

	test('fresh guest welcome uses session-only tags and local smart ranking', async ({ page }: { page: any }) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-carousel-progress')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-headline')).toContainText('Simply ask your', { timeout: 15000 });
		await expect(page.getByTestId('landing-intro-headline')).toContainText('AI team mates', { timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-previous')).toHaveCount(0);
		for (const appId of LANDING_INTRO_HIGHLIGHTED_APPS) {
			await expect(page.locator(`[data-testid="landing-intro-app-icon"][data-app-id="${appId}"]`).first()).toBeVisible({ timeout: 15000 });
		}
		await expect(page.locator('[data-testid="landing-intro-app-icon"][data-app-id="ai"]')).toHaveCount(0);
		await expect.poll(async () => (await landingIntroState(page)).requestLabel, { timeout: 5000 }).toBeTruthy();
		const introState = await landingIntroState(page);
		expect(LANDING_INTRO_REQUESTS).toContain(introState.requestLabel);
		expect(introState.highlightedAppIds).toContain(LANDING_INTRO_REQUEST_APP_IDS.get(introState.requestLabel));
		const guestIntroMetrics = await page.evaluate(() => {
			const banner = document.querySelector('[data-testid="daily-inspiration-banner"]');
			const copy = document.querySelector('[data-testid="landing-intro-expanded"]');
			const headline = document.querySelector('[data-testid="landing-intro-headline"]');
			const bannerRect = banner?.getBoundingClientRect();
			const copyRect = copy?.getBoundingClientRect();
			return {
				bannerHeight: bannerRect?.height ?? 0,
				copyTop: copyRect?.top ?? 0,
				copyBottom: copyRect?.bottom ?? 0,
				bannerTop: bannerRect?.top ?? 0,
				bannerBottom: bannerRect?.bottom ?? 0,
				copyFontSize: headline ? Number.parseFloat(getComputedStyle(headline).fontSize) : 0,
				headlineText: (headline as HTMLElement | null)?.innerText.trim() ?? ''
			};
		});
		expect(guestIntroMetrics.bannerHeight).toBeGreaterThanOrEqual(520);
		expect(guestIntroMetrics.headlineText).toBe(LANDING_INTRO_HEADLINE_TEXT);
		expect(guestIntroMetrics.copyTop).toBeGreaterThanOrEqual(guestIntroMetrics.bannerTop);
		expect(guestIntroMetrics.copyBottom).toBeLessThanOrEqual(guestIntroMetrics.bannerBottom);
		expect(guestIntroMetrics.copyFontSize).toBeGreaterThanOrEqual(32);

		await skipExpandedLandingIntro(page);
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });

		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('Hey there!')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('What are your interests?')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('Explore what you can do:')).toHaveCount(0);
		expect(await page.evaluate(() => window.location.hash)).not.toContain('demo-for-everyone');

		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 15000 });
		expect(await interestTagsPromptGap(page)).toBeGreaterThanOrEqual(8);
		await expect(page.getByTestId('interest-tag-find_apartments')).toHaveAttribute('data-app-id', 'home');
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-skip')).toBeVisible({ timeout: 5000 });

		await page.getByTestId('guest-interest-skip').click();
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('Explore what you can do:')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('What are your interests?')).toHaveCount(0);
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 15000 });
		await expect(firstContinueChatCard(page)).toHaveAttribute('data-chat-id', 'demo-for-everyone', { timeout: 15000 });

		await page.getByTestId('guest-interest-select-interests').click();
		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('What are your interests?')).toBeVisible({ timeout: 5000 });
		expect(await interestTagsPromptGap(page)).toBeGreaterThanOrEqual(8);
		await expect(page.getByText('Explore what you can do:')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);

		const defaultTagOrder = await interestTagOrder(page);
		const defaultRailMetrics = await tagRailMetrics(page);
		const defaultRailSideGaps = await tagRailSideGaps(page);
		expect(defaultRailMetrics.availableTagCount).toBe(10);
		expect(defaultRailMetrics.selectedTagCount).toBe(0);
		expect(defaultRailSideGaps.left).toBeLessThanOrEqual(24);
		expect(defaultRailSideGaps.right).toBeLessThanOrEqual(24);
		expect(await lastTagCenterDeltaAtScrollEnd(page)).toBeLessThanOrEqual(32);
		expect(defaultTagOrder.slice(0, 10)).toEqual(
			expect.arrayContaining([
				'privacy',
				'learning',
				'writing',
				'find_restaurant',
				'find_apartments'
			])
		);
		expect(defaultTagOrder.indexOf('software_development')).toBeGreaterThan(0);

		await page.getByTestId('daily-inspiration-next').click();
		await expect.poll(async () => (await interestTagOrder(page)).join('|'), { timeout: 5000 }).not.toBe(defaultTagOrder.join('|'));
		const reshuffledRailMetrics = await tagRailMetrics(page);
		expect(reshuffledRailMetrics.availableTagCount).toBe(10);
		expect(reshuffledRailMetrics.selectedTagCount).toBe(0);

		await clickInterestTag(page, 'software_development');
		await expect(page.getByTestId('interest-tag-software_development')).toHaveAttribute(
			'data-interest-active',
			'true'
		);
		await expect(page.getByTestId('interest-tag-software_development-check')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('interest-tag-software_development')).toContainText('software development');
		await expect(page.getByText('Sophia')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);
		await clickInterestTag(page, 'privacy');
		await clickInterestTag(page, 'run_code');
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);
		await clickInterestTag(page, 'build_electronics');
		await expect(page.getByTestId('guest-interest-continue')).toBeVisible({ timeout: 5000 });

		const tagOrder = await interestTagOrder(page);
		expect(tagOrder.slice(0, 4)).toEqual(SELECTED_INTEREST_TAGS);
		const selectedRailMetrics = await tagRailMetrics(page);
		const selectedRailSideGaps = await tagRailSideGaps(page);
		expect(selectedRailMetrics.availableTagCount).toBe(10);
		expect(selectedRailMetrics.selectedTagCount).toBe(4);
		expect(selectedRailSideGaps.left).toBeLessThanOrEqual(24);
		expect(selectedRailSideGaps.right).toBeLessThanOrEqual(24);
		expect(await lastTagCenterDeltaAtScrollEnd(page)).toBeLessThanOrEqual(32);
		expect(await firstAvailableTagCenterDelta(page)).toBeLessThanOrEqual(32);
		expect(tagOrder).toEqual(
			expect.arrayContaining(['privacy', 'run_code', 'build_electronics', 'diy_projects'])
		);
		expect(tagOrder).toContain('electrical_engineering');
		await expect(page.getByTestId('interest-tag-electrical_engineering')).toContainText('electronics');
		await expect(page.getByText('Elton')).toHaveCount(0);

		const storageStateBeforeContinue = await page.evaluate((key: string) => ({
			sessionValue: sessionStorage.getItem(key),
			localValue: localStorage.getItem(key)
		}), GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
		expect(storageStateBeforeContinue.localValue).toBeNull();
		expect(storageStateBeforeContinue.sessionValue).toBeNull();

		await page.getByTestId('guest-interest-continue').click();
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('Explore what you can do:')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('What are your interests?')).toHaveCount(0);
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		expect(await page.getByTestId('message-editor').evaluate((editor: HTMLElement) => editor.contains(document.activeElement))).toBe(false);
		const storageStateAfterContinue = await page.evaluate((key: string) => ({
			sessionValue: sessionStorage.getItem(key),
			localValue: localStorage.getItem(key)
		}), GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
		expect(storageStateAfterContinue.localValue).toBeNull();
		expect(storageStateAfterContinue.sessionValue).toContain('software_development');
		expect(storageStateAfterContinue.sessionValue).toContain('privacy');
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 15000 });
		await expect(firstContinueChatCard(page)).toHaveAttribute('data-chat-id', 'demo-for-everyone', { timeout: 15000 });
		await expect(page.getByTestId('example-chat-badge').first()).toContainText('Example chat', { timeout: 15000 });
		await page.getByTestId('message-editor').click();
		await expect(page.getByTestId('suggestions-wrapper')).toBeVisible({ timeout: 15000 });

		const suggestionIds = await visibleSuggestionIds(page);
		expect(suggestionIds.slice(0, 5)).toEqual(
			expect.arrayContaining([
				'chat.new_chat_suggestions.learn_coding',
				'chat.new_chat_suggestions.use_openmates_cli_api'
			])
		);
		await page.keyboard.type('coding');
		await expect.poll(async () => await visibleSuggestionIds(page), { timeout: 5000 }).toContain(
			'chat.new_chat_suggestions.learn_coding'
		);
		expect(await visibleSuggestionIds(page)).not.toContain('chat.new_chat_suggestions.cover_letter');

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0, { timeout: 15000 });
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('Explore what you can do:')).toBeVisible({ timeout: 15000 });
		await expect(firstContinueChatCard(page)).toHaveAttribute('data-chat-id', 'demo-for-everyone', { timeout: 15000 });
		await page.getByTestId('guest-interest-select-interests').click();
		await expect(page.getByText('What are your interests?')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('interest-tag-software_development')).toHaveAttribute(
			'data-interest-active',
			'true',
			{ timeout: 15000 }
		);
		expect(await page.evaluate((key: string) => localStorage.getItem(key), GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toBeNull();
	});

	test('fresh guest sees default suggestions when focusing composer before selecting interests', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1280, height: 800 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await skipExpandedLandingIntro(page);

		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);

		await page.getByTestId('message-editor').click();
		await expect(page.getByTestId('suggestions-wrapper')).toBeVisible({ timeout: 15000 });

		const suggestionIds = await visibleSuggestionIds(page);
		expect(suggestionIds.length).toBeGreaterThan(0);
		expect(suggestionIds.every((id) => id.startsWith('chat.new_chat_suggestions.'))).toBe(true);
	});

	test('mobile guest intro alternates copy and video', async ({ page }: { page: any }) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('landing-intro-headline')).toContainText('your AI team mates', { timeout: 15000 });
		const mobileIntroMetrics = await page.getByTestId('daily-inspiration-banner').evaluate((banner: HTMLElement) => ({
			height: banner.getBoundingClientRect().height,
			containerHeight: document.querySelector<HTMLElement>('[data-testid="active-chat-container"]')?.getBoundingClientRect().height ?? 0
		}));
		expect(mobileIntroMetrics.height).toBeGreaterThanOrEqual(mobileIntroMetrics.containerHeight * 0.65);

		await skipExpandedLandingIntro(page);
		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 15000 });
		expect(await lastTagCenterDeltaAtScrollEnd(page)).toBeLessThanOrEqual(32);
	});
});
