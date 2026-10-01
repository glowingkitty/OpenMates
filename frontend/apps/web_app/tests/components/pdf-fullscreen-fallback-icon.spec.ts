import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
test('PDF fullscreen fallback keeps its 80px tile centered', async ({ page }) => {
	await page.goto('/dev/preview/embeds/pdf/PDFEmbedFullscreen?theme=light&background=%23dbeafe&width=390&chrome=0');
	await waitForComponentPreview(page);

	const content = page.locator('.pdf-info-fallback');
	const icon = content.locator('.icon_rounded.pdf.large');
	await expect(content).toBeVisible({ timeout: 30_000 });
	await expect(icon).toBeVisible();
	await expect(icon).toHaveCSS('position', 'relative');
	await expect(icon).toHaveCSS('background-size', '100% 100%');
	const glyphSize = await icon.evaluate((element) => getComputedStyle(element, '::after').backgroundSize);
	expect(glyphSize).toBe('40px 40px');
	const contentBox = await content.boundingBox();
	const iconBox = await icon.boundingBox();
	expect(contentBox).not.toBeNull();
	expect(iconBox).not.toBeNull();
	expect(iconBox!.width).toBe(80);
	expect(iconBox!.height).toBe(80);
	expect(Math.abs(iconBox!.x + iconBox!.width / 2 - (contentBox!.x + contentBox!.width / 2))).toBeLessThan(1);
});
