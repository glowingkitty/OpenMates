import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

for (const { width, variant, initialBody } of [
  { width: 1100, variant: '', initialBody: 'Meet by the south gate at ten.' },
  { width: 390, variant: 'focusedChild', initialBody: 'Bring labelled seeds.' },
  { width: 1100, variant: 'inlineResults', initialBody: 'Meet by the south gate at ten.' },
]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  test(`mail search reads ${variant || 'saved child results'} at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/embeds/mail/MailSearchEmbedFullscreen?chrome=0&theme=light&width=${width}${variant ? `&variant=${variant}` : ''}`);
    await waitForComponentPreview(page);

    const reader = page.getByRole('article');
    await expect(reader).toHaveText(initialBody);
    const results = page.getByTestId('mail-search-result');
    await expect(results).toHaveCount(2);
    const garden = results.filter({ hasText: 'Garden volunteers' });
    const seeds = results.filter({ hasText: 'Seed swap' });
    await expect(garden.getByText('Garden volunteers', { exact: true })).toBeVisible();
    await expect(garden.getByText('Meet by the south gate at ten.', { exact: true })).toBeVisible();
    if (variant === 'focusedChild') {
      await garden.click();
      await expect(reader).toHaveText('Meet by the south gate at ten.');
    }
    await seeds.focus();
    await expect(seeds).toBeFocused();
    await seeds.press('Enter');
    await expect(reader).toHaveText('Bring labelled seeds.');
    await expect(reader.locator('strong')).toHaveText('labelled seeds');
    await expect(reader.locator('form, input')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);

    await testInfo.attach(`mail-reader-${variant || 'saved'}-${width}`, {
      body: await page.screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    });
  });
}
