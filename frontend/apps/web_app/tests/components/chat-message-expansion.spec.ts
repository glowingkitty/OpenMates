// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 820]) {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  test(`optimistic full message stays expanded across status refresh at ${width}px`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: Math.max(1280, width + 80), height: 1100 });
    const params = new URLSearchParams({ chrome: '0', width: String(width), props: JSON.stringify({ containerWidth: width }) });
    await page.goto(`/dev/preview/ChatMessageExpansionPreview?${params}`);
    const canvas = await waitForComponentPreview(page);
    const message = canvas.getByTestId('expansion-message');
    await expect(message).not.toContainText('Synthetic Practice alpha');
    await message.getByRole('button', { name: 'Show full message', exact: true }).click();
    await expect(message).toContainText('Synthetic Practice alpha');
    await expect(message.getByRole('button', { name: 'Show less', exact: true })).toBeVisible();
    await expect(message).toContainText('[EMAIL_PREVIEW]');
    await expect(message).not.toContainText('person@example.test');
    for (const status of ['processing', 'synced']) {
      await canvas.getByRole('button', { name: `Refresh ${status}`, exact: true }).click();
      await expect(message).toHaveAttribute('data-status', status);
      await expect(message).toContainText('Synthetic Practice alpha');
      await expect(message.getByRole('button', { name: 'Show less', exact: true })).toBeVisible();
    }
    await canvas.getByRole('button', { name: 'Toggle private data', exact: true }).click();
    await expect(message).toContainText('person@example.test');
    await canvas.getByRole('button', { name: 'Toggle private data', exact: true }).click();
    await expect(message).toContainText('[EMAIL_PREVIEW]');
    await expect(message).not.toContainText('person@example.test');
    await message.getByRole('button', { name: 'Show less', exact: true }).click();
    await expect(message).not.toContainText('Synthetic Practice alpha');
    await expect(message.getByRole('button', { name: 'Show full message', exact: true })).toBeVisible();
  });
}
