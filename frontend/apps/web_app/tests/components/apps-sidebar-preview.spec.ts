// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');
// Four theme/width navigations share one case, including the cold Vite mount.
test.setTimeout(120_000);

test.describe('Apps sidebar bare preview', () => {
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency
  test('long titles remain inside separate rows, with working search and close controls', async ({ page }: { page: Page }) => {
    for (const theme of ['light', 'dark']) {
      for (const width of [304, 343]) {
        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto(`/dev/preview/apps/AppsSidebar?chrome=0&width=${width}&theme=${theme}`, { waitUntil: 'domcontentloaded' });
        await waitForComponentPreview(page);
        const sidebar = page.getByTestId('apps-sidebar');
        await expect(sidebar.locator('button.entry')).toHaveCount(5);
        const geometry = await sidebar.evaluate(element => {
          const rows = [...element.querySelectorAll<HTMLElement>('button.entry')];
          return {
            overflow: element.scrollWidth > element.clientWidth,
            rows: rows.map(row => {
              const box = row.getBoundingClientRect();
              const title = row.querySelector<HTMLElement>('.entry-title')!;
              const titleBox = title.getBoundingClientRect();
              return { top: box.top, bottom: box.bottom, titleTop: titleBox.top, titleBottom: titleBox.bottom,
                height: titleBox.height, lineHeight: parseFloat(getComputedStyle(title).lineHeight),
                clamp: getComputedStyle(title).webkitLineClamp };
            }),
          };
        });
        expect(geometry.overflow).toBe(false);
        geometry.rows.forEach((row, index) => {
          expect(row.clamp).toBe('2');
          expect(row.height).toBeLessThanOrEqual(row.lineHeight * 2 + 1);
          expect(row.titleTop).toBeGreaterThanOrEqual(row.top);
          expect(row.titleBottom).toBeLessThanOrEqual(row.bottom);
          if (index) expect(row.top).toBeGreaterThanOrEqual(geometry.rows[index - 1].bottom);
        });
        const selection = page.evaluate(() => new Promise(resolve => window.addEventListener('apps-sidebar-preview-select', event => resolve((event as CustomEvent).detail), { once: true })));
        await sidebar.getByTestId('apps-sidebar-saved').locator('button').first().click();
        expect(await selection).toEqual({ kind: 'embed', id: 'saved-embed' });
        await sidebar.getByRole('button', { name: 'Search', exact: true }).click();
        const search = sidebar.getByRole('searchbox');
        await expect(search).toBeFocused();
        await search.fill('pollinators');
        await expect(sidebar.locator('button.entry')).toHaveCount(1);
        await expect(sidebar.locator('button.entry')).toContainText('pollinators');
        await search.press('Escape');
        await expect(sidebar.locator('button.entry')).toHaveCount(5);
        const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('apps-sidebar-preview-close', () => resolve(), { once: true })));
        await sidebar.getByTestId('apps-sidebar-close').click();
        await closed;
      }
    }
  });
});
