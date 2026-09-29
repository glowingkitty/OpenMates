import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1280]) {
	// contract-test: tooling
	test(`nightly digest shows missing web and native coverage at ${width}px`, async ({ page }) => {
		await page.setViewportSize({ width, height: 844 });
		await page.goto(`/dev/preview/status/DailyTestDigest?theme=light&background=%23dbeafe&width=${width}&chrome=0`);
		await waitForComponentPreview(page);
		const digest = page.getByTestId('daily-test-digest');
		await expect(digest).toBeVisible();
		await expect(digest).toContainText('6,772 run · 172 failed');
		await expect(digest).toContainText('Spec inventory unknown; selection did not finish');
		await expect(digest).toContainText('No scheduled native run');
		await expect(digest.getByRole('link', { name: 'Full results' })).toHaveAttribute('href', /2026-09-28\?format=html/);
		const geometry = await digest.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
		expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
		await expect(page.locator('[data-testid="preview-toolbar"]')).toHaveCount(0);
	});
}

// contract-test: tooling
test('shows a missed latest run even when the old result passed', async ({ page }) => {
	await page.goto('/dev/preview/status/DailyTestDigest?variant=Stale&theme=light&background=%23dbeafe&width=390&chrome=0');
	await waitForComponentPreview(page);
	const digest = page.getByTestId('daily-test-digest');
	await expect(digest).toContainText('Stale result: no report for the latest scheduled run');
	await expect(digest).toContainText('PASSED');
});
