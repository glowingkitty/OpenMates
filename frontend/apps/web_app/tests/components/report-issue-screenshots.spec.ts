// playwright-account: not_required reason=isolated_component_preview
/**
 * Report Issue screenshot thumbnails: 0, 1 and 3 attached images, the count
 * and the per-item remove buttons, at phone width.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

async function open(page: import('@playwright/test').Page, variant: string) {
	await page.goto(`/dev/preview/settings/ReportIssueScreenshots?chrome=0&theme=light&width=390&variant=${variant}`);
	await waitForComponentPreview(page);
}

// contract-test: direct surface=gui.web assertions=issue-reporting.form.single-text-quick-actions
test('shows nothing for zero, then a count and removable thumbnails for one and three screenshots', async ({ page }) => {
	await open(page, 'none');
	await expect(page.getByTestId('screenshot-section')).toHaveCount(0);

	await open(page, 'one');
	await expect(page.getByTestId('screenshot-preview')).toHaveCount(1);
	await expect(page.getByTestId('screenshot-count')).toHaveText('1/5');
	await expect(page.getByTestId('screenshot-remove')).toHaveCount(1);
	await test.info().attach('report-issue-screenshots-one', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});

	await open(page, 'three');
	await expect(page.getByTestId('screenshot-preview')).toHaveCount(3);
	await expect(page.getByTestId('screenshot-preview').nth(2)).toHaveAttribute('data-index', '2');
	await expect(page.getByTestId('screenshot-count')).toHaveText('3/5');
	await expect(page.getByTestId('screenshot-remove')).toHaveCount(3);
	await test.info().attach('report-issue-screenshots-three', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});

	await open(page, 'limit');
	await expect(page.getByTestId('screenshot-count')).toHaveText('5/5');
	const removeBox = await page.getByTestId('screenshot-remove').first().boundingBox();
	expect(removeBox?.width).toBeLessThanOrEqual(24);
	expect(removeBox?.height).toBeLessThanOrEqual(24);
	await expect(page.getByTestId('screenshot-error')).toHaveText('You can attach up to 5 screenshots.');
	await test.info().attach('report-issue-screenshots-limit', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});
});
