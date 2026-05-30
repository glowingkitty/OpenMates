import { expect, test } from './helpers/cookie-audit';

/**
 * Playwright E2E Tests for the InteractiveQuestions system.
 * Runs against the dev preview router to verify layout rendering, Clear/Send button states,
 * and user interactions.
 *
 * Architecture: Svelte 5 / Playwright Integration Tests
 */
test.describe('InteractiveQuestions System', () => {
	test.beforeEach(async ({ page }) => {
		// Navigate directly to the component's unauthenticated dev preview route
		const response = await page.goto('/dev/preview/interactive_questions/InteractiveQuestionContainer', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);
		// Wait for SvelteKit client hydration
		await page.waitForTimeout(2000);
	});

	test('renders choice single-select question, handles selections and clear actions', async ({ page }) => {
		// Verify type badge and question title are visible
		await expect(page.locator('.type-badge.choice-badge')).toContainText('Choice');
		await expect(page.locator('.question-title')).toBeVisible();

		// Verify option list records exist
		const options = page.locator('.option-item');
		await expect(options).toHaveCount(3);

		// Send button should be disabled by default (no selection made)
		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).toHaveClass(/disabled/);

		// Click the first option
		await options.first().click();

		// Send button should become active
		await expect(sendBtn).not.toHaveClass(/disabled/);

		// Click 'Clear'
		await page.locator('.btn-clear').click();

		// Send button should be disabled again
		await expect(sendBtn).toHaveClass(/disabled/);
	});

	test('supports keyboard navigation for accessible choice selections', async ({ page }) => {
		const options = page.locator('.option-item');
		const sendBtn = page.locator('.btn-send');

		// Focus the second choice option and press Enter to select it
		await options.nth(1).focus();
		await page.keyboard.press('Enter');

		// Choice should be selected, unlocking the Send button
		await expect(options.nth(1)).toHaveClass(/selected/);
		await expect(sendBtn).not.toHaveClass(/disabled/);
	});
});
