/**
 * Focused deployed checks for standalone MessageInput component rendering.
 * Keeps composer visual regressions separate from the full preview workflow.
 * Uses the chrome-free component route as the deterministic render surface.
 * Full chat-flow coverage remains in the broader composer specifications.
 */
import { expect, test } from './helpers/cookie-audit';

// contract-test-file: tooling
// proof-video: not_required reason=tooling

test.describe('MessageInput component preview', () => {
	test('composer controls have no resting shadow and a gentle hover shadow', async ({ page }) => {
		const params = new URLSearchParams({
			theme: 'light',
			background: '#dbeafe',
			width: '680',
			chrome: '0'
		});

		await page.goto(`/dev/preview/enter_message/MessageInput?${params}`, {
			waitUntil: 'networkidle'
		});
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true'
		);

		const selector = page.getByTestId('composer-model-selector');
		await expect(selector).toBeVisible();
		const restingFilters = await selector.evaluate((element) =>
			[element, ...element.querySelectorAll('*')]
				.map((node) => window.getComputedStyle(node).filter)
				.filter((filter) => filter !== 'none')
		);
		expect(restingFilters).toEqual([]);

		await selector.hover();
		await expect
			.poll(() => selector.evaluate((element) => window.getComputedStyle(element).filter))
			.toContain('drop-shadow');
	});
});
