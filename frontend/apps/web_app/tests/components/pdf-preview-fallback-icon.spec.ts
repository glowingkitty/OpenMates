import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
test('PDF fallback icon stays centered inside the bare preview card', async ({ page }) => {
	await page.goto('/dev/preview/embeds/pdf/PDFEmbedPreview?theme=light&background=%23dbeafe&width=390&chrome=0');
	await waitForComponentPreview(page);

	const content = page.locator('.pdf-icon-center');
	const icon = content.locator('.icon_rounded.pdf');
	await expect(icon).toBeVisible();
	await expect(icon).toHaveCSS('position', 'relative');
	await expect(icon).toHaveCSS('background-size', '100% 100%');
	const glyphSize = await icon.evaluate((element) => getComputedStyle(element, '::after').backgroundSize);
	expect(glyphSize).toBe('26px 26px');
	const contentBox = await content.boundingBox();
	const iconBox = await icon.boundingBox();
	expect(contentBox).not.toBeNull();
	expect(iconBox).not.toBeNull();
	expect(iconBox!.width).toBe(52);
	expect(iconBox!.height).toBe(52);
	expect(Math.abs(iconBox!.x + iconBox!.width / 2 - (contentBox!.x + contentBox!.width / 2))).toBeLessThan(1);
	expect(Math.abs(iconBox!.y + iconBox!.height / 2 - (contentBox!.y + contentBox!.height / 2))).toBeLessThan(1);
	await page.screenshot({ path: test.info().outputPath('pdf-preview-fallback-icon.png') });
});
