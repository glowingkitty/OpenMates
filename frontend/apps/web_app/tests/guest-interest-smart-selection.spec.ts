/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Guest interest smart-selection E2E coverage.
 *
 * Verifies the logged-out landing contract from
 * docs/specs/guest-interest-smart-selection/spec.yml: new visitors stay on the
 * welcome screen, see the OpenMates intro hero, select session-only interest
 * tags, and get deterministic developer/privacy suggestions.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const GUEST_TOPIC_PREFERENCES_STORAGE_KEY = 'openmates.guest_interest_tags.v1';

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

async function tagRailEndGap(page: any): Promise<number> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
		const tags = Array.from(rail.querySelectorAll<HTMLElement>('button[data-testid^="interest-tag-"]'));
		const lastTag = tags[tags.length - 1];
		if (!lastTag) return Number.POSITIVE_INFINITY;
		rail.scrollLeft = rail.scrollWidth;
		const railRect = rail.getBoundingClientRect();
		const lastRect = lastTag.getBoundingClientRect();
		return Math.max(0, railRect.right - lastRect.right);
	});
}

async function tagOffsetFromRail(page: any, tagId: string): Promise<number> {
	return page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement, id: string) => {
		const tag = rail.querySelector<HTMLElement>(`[data-testid="interest-tag-${id}"]`);
		if (!tag) throw new Error(`${id} tag not found`);
		return tag.getBoundingClientRect().left - rail.getBoundingClientRect().left;
	}, tagId);
}

test.describe('Guest interest smart selection', () => {
	test('fresh guest welcome uses session-only tags and local smart ranking', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('Hey there!')).toBeVisible({ timeout: 15000 });
		await expect(page.getByText('What are you interested in?')).toBeVisible({ timeout: 15000 });
		expect(await page.evaluate(() => window.location.hash)).not.toContain('demo-for-everyone');

		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-carousel-progress')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('guest-intro-video')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('guest-intro-ai-icon')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('guest-intro-copy')).toContainText('AI team mates.', { timeout: 15000 });
		const guestIntroMetrics = await page.evaluate(() => {
			const banner = document.querySelector('[data-testid="daily-inspiration-banner"]');
			const copy = document.querySelector('[data-testid="guest-intro-copy"]');
			const copyLine = document.querySelector('.guest-intro-copy-line');
			const videoShell = document.querySelector('[data-testid="guest-intro-video-shell"]');
			const bannerRect = banner?.getBoundingClientRect();
			const copyRect = copy?.getBoundingClientRect();
			return {
				bannerHeight: bannerRect?.height ?? 0,
				copyTop: copyRect?.top ?? 0,
				copyBottom: copyRect?.bottom ?? 0,
				bannerTop: bannerRect?.top ?? 0,
				bannerBottom: bannerRect?.bottom ?? 0,
				copyFontSize: copyLine ? Number.parseFloat(getComputedStyle(copyLine).fontSize) : 0,
				videoHeight: videoShell?.getBoundingClientRect().height ?? 0
			};
		});
		expect(guestIntroMetrics.bannerHeight).toBeGreaterThanOrEqual(230);
		expect(guestIntroMetrics.bannerHeight).toBeLessThanOrEqual(300);
		expect(guestIntroMetrics.copyTop).toBeGreaterThanOrEqual(guestIntroMetrics.bannerTop);
		expect(guestIntroMetrics.copyBottom).toBeLessThanOrEqual(guestIntroMetrics.bannerBottom);
		expect(guestIntroMetrics.copyFontSize).toBeGreaterThanOrEqual(32);
		expect(guestIntroMetrics.videoHeight).toBeGreaterThanOrEqual(guestIntroMetrics.bannerHeight * 0.75);
		expect(guestIntroMetrics.videoHeight).toBeLessThanOrEqual(guestIntroMetrics.bannerHeight);

		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('interest-tag-find_apartments')).toHaveAttribute('data-app-id', 'home');
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);

		const defaultTagOrder = await interestTagOrder(page);
		const defaultRailMetrics = await tagRailMetrics(page);
		expect(defaultRailMetrics.availableTagCount).toBe(10);
		expect(defaultRailMetrics.selectedTagCount).toBe(0);
		expect(await tagRailEndGap(page)).toBeLessThanOrEqual(24);
		expect(defaultTagOrder.slice(0, 6)).toEqual(
			expect.arrayContaining([
				'protect_my_privacy',
				'learn_anything',
				'summarize_documents',
				'local_life',
				'find_apartments'
			])
		);
		expect(defaultTagOrder.indexOf('software_development')).toBeGreaterThan(0);

		await page.getByTestId('guest-interest-rail').evaluate((rail: HTMLElement) => {
			const tag = rail.querySelector<HTMLElement>('[data-testid="interest-tag-software_development"]');
			if (!tag) throw new Error('software_development tag not found');
			const previousScrollBehavior = rail.style.scrollBehavior;
			rail.style.scrollBehavior = 'auto';
			rail.scrollLeft = Math.max(0, tag.offsetLeft - rail.clientWidth / 2 + tag.offsetWidth / 2);
			rail.style.scrollBehavior = previousScrollBehavior;
		});
		const tagOffsetBeforeTagClick = await tagOffsetFromRail(page, 'software_development');
		await page.getByTestId('interest-tag-software_development').click();
		await page.waitForTimeout(250);
		expect(Math.abs((await tagOffsetFromRail(page, 'software_development')) - tagOffsetBeforeTagClick)).toBeLessThanOrEqual(8);
		await expect(page.getByTestId('interest-tag-software_development')).toHaveAttribute(
			'data-interest-active',
			'true'
		);
		await expect(page.getByTestId('interest-tag-software_development-check')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('guest-interest-continue')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);

		const tagOrder = await interestTagOrder(page);
		expect(tagOrder).toContain('software_development');
		const selectedRailMetrics = await tagRailMetrics(page);
		expect(selectedRailMetrics.availableTagCount).toBe(10);
		expect(selectedRailMetrics.selectedTagCount).toBe(1);
		expect(await tagRailEndGap(page)).toBeLessThanOrEqual(24);
		expect(tagOrder).toEqual(
			expect.arrayContaining(['use_the_cli', 'open_source', 'read_developer_docs', 'run_code'])
		);
		expect(tagOrder).toContain('find_apartments');

		const storageStateBeforeContinue = await page.evaluate((key: string) => ({
			sessionValue: sessionStorage.getItem(key),
			localValue: localStorage.getItem(key)
		}), GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
		expect(storageStateBeforeContinue.localValue).toBeNull();
		expect(storageStateBeforeContinue.sessionValue).toBeNull();

		await page.getByTestId('guest-interest-continue').click();
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		const storageStateAfterContinue = await page.evaluate((key: string) => ({
			sessionValue: sessionStorage.getItem(key),
			localValue: localStorage.getItem(key)
		}), GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
		expect(storageStateAfterContinue.localValue).toBeNull();
		expect(storageStateAfterContinue.sessionValue).toContain('software_development');
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 15000 });
		await expect(firstContinueChatCard(page)).toHaveAttribute(
			'data-chat-id',
			'demo-for-developers',
			{ timeout: 15000 }
		);
		await expect(page.getByTestId('suggestions-wrapper')).toBeVisible({ timeout: 15000 });

		const suggestionIds = await visibleSuggestionIds(page);
		expect(suggestionIds.slice(0, 5)).toEqual(
			expect.arrayContaining([
				'chat.new_chat_suggestions.learn_coding',
				'chat.new_chat_suggestions.use_openmates_cli_api'
			])
		);

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('interest-tag-software_development')).toHaveAttribute(
			'data-interest-active',
			'true',
			{ timeout: 15000 }
		);
		expect(await page.evaluate((key: string) => localStorage.getItem(key), GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toBeNull();
	});
});
