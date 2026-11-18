// playwright-account: not_required reason=isolated_component_preview
// Application card without a stored screenshot (apps built from private Project
// files never get one): it shows a start-preview call, not a loading skeleton.
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const PREVIEW = '/dev/preview/embeds/code/ApplicationEmbedPreview';

test.describe('application preview card', () => {
	for (const variant of ['', 'mobile']) {
		// contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
		test(`card without a screenshot invites starting the preview${variant ? ` (${variant})` : ''}`, async ({ page }, testInfo) => {
			const query = new URLSearchParams({ theme: 'light', width: variant ? '390' : '900', chrome: '0' });
			if (variant) query.set('variant', variant);
			await page.goto(`${PREVIEW}?${query}`, { waitUntil: 'domcontentloaded' });
			await waitForComponentPreview(page);

			const placeholder = page.getByTestId('application-preview-placeholder');
			await expect(placeholder).toBeVisible();
			await expect(placeholder).toContainText('Start preview');
			await expect(page.getByTestId('application-preview-play-overlay')).toBeVisible();
			await expect(page.getByTestId('application-preview-screenshot-image')).toHaveCount(0);
			// The label and the play button must not overlap.
			const label = await page.getByTestId('application-preview-start-label').boundingBox();
			const play = await page.getByTestId('application-preview-play-overlay').boundingBox();
			expect(label && play && (label.y >= play.y + play.height || label.y + label.height <= play.y)).toBe(true);
			// The label sits fully inside the clipping screenshot frame (not cut off at its edge).
			const area = await page.getByTestId('application-preview-screenshot').boundingBox();
			expect(label && area && label.y >= area.y && label.y + label.height <= area.y + area.height).toBe(true);

			await testInfo.attach(`application-card-placeholder${variant ? `-${variant}` : ''}`, {
				body: await page.getByTestId('application-preview-details').screenshot(),
				contentType: 'image/png'
			});
		});
	}
});
