import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/sheets/SheetEmbedFullscreen';

for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  test(`sheet gutter filter stays compact and sorting/filtering work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${PREVIEW}?theme=light&background=%23dbeafe&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    const table = page.locator('table.spreadsheet');
    const toggle = page.getByRole('button', { name: 'Toggle column filters', exact: true });
    const rows = table.locator('tbody tr');
    await expect(rows).toHaveCount(8);
    await expect(toggle.locator('svg')).toBeVisible();

    const assertCompactGutter = async () => {
      await expect.poll(async () => toggle.evaluate((button) => {
        const rect = button.getBoundingClientRect();
        const gutter = button.closest('th')!.getBoundingClientRect();
        const style = getComputedStyle(button);
        return {
          width: Math.round(rect.width * 100) / 100,
          height: Math.round(rect.height * 100) / 100,
          contained: rect.left >= gutter.left && rect.right <= gutter.right &&
            rect.top >= gutter.top && rect.bottom <= gutter.bottom,
          padding: style.padding,
          filter: style.filter,
        };
      })).toEqual({ width: 22, height: 22, contained: true, padding: '0px', filter: 'none' });
    };

    await assertCompactGutter();
    await toggle.hover();
    await assertCompactGutter();
    await toggle.focus();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Shift+Tab');
    await expect(toggle).toBeFocused();
    await expect.poll(() => toggle.evaluate((button) => getComputedStyle(button).outlineStyle)).not.toBe('none');
    await toggle.press('Space');
    await expect(page.getByPlaceholder('Name', { exact: true })).toBeVisible();
    await assertCompactGutter();

    await page.getByPlaceholder('Name', { exact: true }).fill('carol');
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Carol Williams');
    await page.getByRole('button', { name: 'Clear all filters', exact: true }).click();
    await expect(rows).toHaveCount(8);
    await expect(page.getByPlaceholder('Name', { exact: true })).toHaveValue('');

    const nameHeader = table.locator('th.col-header').filter({ hasText: 'Name' });
    await nameHeader.click();
    await expect(rows.first()).toContainText('Alice Johnson');
    await nameHeader.click();
    await expect(rows.first()).toContainText('Henry Davis');
    await nameHeader.click();
    await expect(rows.first()).toContainText('Alice Johnson');
    await expect(nameHeader.locator('.sort-icon-active')).toHaveCount(0);

    await page.getByPlaceholder('Name', { exact: true }).fill('missing person');
    await expect(table.getByText('No rows match the current filters', { exact: true })).toBeVisible();
    await toggle.hover();
    await page.mouse.down();
    try {
      await assertCompactGutter();
    } finally {
      await page.mouse.up();
    }
    await expect(page.getByPlaceholder('Name', { exact: true })).toHaveCount(0);
    await expect(rows).toHaveCount(8);
    await assertCompactGutter();
  });
}
