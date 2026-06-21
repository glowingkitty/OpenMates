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
	return page.getByTestId('guest-interest-rail').locator('[data-testid^="interest-tag-"]').evaluateAll(
		(nodes: Element[]) => nodes.map((node) => (node.getAttribute('data-testid') || '').replace('interest-tag-', ''))
	);
}

async function visibleSuggestionIds(page: any): Promise<string[]> {
	return page.getByTestId('new-chat-suggestion-card').evaluateAll(
		(nodes: Element[]) => nodes.map((node) => node.getAttribute('data-suggestion-id') || '')
	);
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
		await expect(page.getByTestId('guest-intro-copy')).toContainText('AI team mates.', { timeout: 15000 });

		await expect(page.getByTestId('guest-interest-tags')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('interest-tag-find_apartments')).toHaveAttribute('data-app-id', 'home');
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);

		const defaultTagOrder = await interestTagOrder(page);
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

		await page.getByTestId('interest-tag-software_development').click();
		await expect(page.getByTestId('interest-tag-software_development')).toHaveAttribute(
			'data-interest-active',
			'true'
		);
		await expect(page.getByTestId('interest-tag-software_development-check')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('guest-interest-continue')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('recent-chats-scroll-container')).toHaveCount(0);
		await expect(page.getByTestId('new-chat-suggestion-card')).toHaveCount(0);

		const tagOrder = await interestTagOrder(page);
		expect(tagOrder[0]).toBe('software_development');
		expect(tagOrder.slice(1, 7)).toEqual(
			expect.arrayContaining(['use_the_cli', 'open_source', 'read_developer_docs', 'run_code'])
		);
		expect(tagOrder).toContain('find_apartments');

		const storageState = await page.evaluate((key: string) => ({
			sessionValue: sessionStorage.getItem(key),
			localValue: localStorage.getItem(key)
		}), GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
		expect(storageState.localValue).toBeNull();
		expect(storageState.sessionValue).toContain('software_development');

		await page.getByTestId('guest-interest-continue').click();
		await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: 15000 });
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
