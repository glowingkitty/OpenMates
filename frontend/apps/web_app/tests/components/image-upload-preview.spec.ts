import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant: string) =>
	`/dev/preview/embeds/images/ImageEmbedPreview?variant=${variant}&theme=light&background=%23dbeafe&width=390&chrome=0`;

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
test('draft image preview keeps upload, completed, and error states legible', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	for (const [variant, status, subtitle] of [
		['uploading', 'processing', /Uploading/i],
		['uploadedDraft', 'finished', null],
		['error', 'error', /Upload failed: file too large/i]
	] as const) {
		await test.step(variant, async () => {
			await page.goto(preview(variant));
			await waitForComponentPreview(page);
			const card = page.getByTestId('embed-preview').filter({ has: page.getByRole('img', { name: 'golden-gate-sunset.jpg' }) });
			await expect(card).toBeVisible();
			await expect(card).toHaveAttribute('data-status', status);
			await expect(card.getByRole('img', { name: 'golden-gate-sunset.jpg' })).toBeVisible();
			// Result cards show the status as the card's source line; a finished picture is shown full-bleed without text.
			if (subtitle) await expect(card.getByTestId('result-card-content')).toContainText(subtitle);
			else await expect(card.getByTestId('result-card-content')).not.toContainText(/Uploading|Upload failed/i);
			const stop = card.getByTestId('image-upload-stop');
			if (variant === 'uploading') {
				await expect(stop).toBeVisible();
				await expect(stop).toHaveAccessibleName(/stop/i);
				await expect(stop).toHaveCSS('width', '36px');
				await expect(stop).toHaveCSS('height', '36px');
			} else {
				await expect(card.getByRole('button', { name: /stop/i })).toHaveCount(0);
			}
			const bounds = await card.boundingBox();
			expect(bounds).not.toBeNull();
			expect(bounds!.x).toBeGreaterThanOrEqual(0);
			expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
			await testInfo.attach(`image-upload-${variant}`, {
				body: await page.screenshot(),
				contentType: 'image/png'
			});
		});
	}
});
