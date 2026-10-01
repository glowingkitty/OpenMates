// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('../helpers/cookie-audit');

const preview = (width: number, variant?: string, theme = 'light') =>
  `/dev/preview/workspace/WorkflowSidebar?${new URLSearchParams({
    theme, background: theme === 'dark' ? '#171717' : '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

for (const [width, theme] of [[325, 'light'], [320, 'dark']] as const) {
  // contract-test: direct surface=gui.web assertions=workspace-shell.start.chat-visual-parity,workflows-ui.responsive-accessible-reachable
  test(`workflow sidebar has compact chat-style rows and a visible close control at ${width}px in ${theme} mode`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(preview(width, undefined, theme), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
    const sidebar = page.getByTestId('workflows-sidebar');
    const rows = sidebar.getByTestId('workflow-sidebar-row');
    const close = sidebar.getByTestId('workflow-sidebar-close');
    await expect(sidebar).toBeVisible();
    await expect(rows).toHaveCount(3);
    await expect(close).toBeVisible();
    await expect(close.locator('.icon_close')).toBeVisible();
    await expect(close).toHaveAccessibleName('Close');
    await expect(rows.first()).toHaveAttribute('aria-current', 'page');
    await expect(rows.nth(1)).not.toHaveAttribute('aria-current', 'page');
    await expect(rows.first().locator('.workflow-sidebar-icon svg')).toBeVisible();
    await expect(rows.nth(1)).toContainText('Draft · Weekly at 10:00');
    const geometry = await rows.evaluateAll((elements: HTMLElement[]) => elements.map(element => {
      const row = element.getBoundingClientRect();
      const title = element.querySelector('.workflow-sidebar-title')!.getBoundingClientRect();
      const icon = element.querySelector('.workflow-sidebar-icon')!.getBoundingClientRect();
      return { width: row.width, height: row.height, titleX: title.x, iconRight: icon.right, textAlign: getComputedStyle(element).textAlign };
    }));
    for (const item of geometry) {
      expect(item.height).toBeLessThanOrEqual(64);
      expect(item.titleX).toBeGreaterThan(item.iconRight);
      expect(item.textAlign).toBe('start');
    }
    await rows.nth(1).hover();
    await expect(rows.nth(1)).toHaveCSS('cursor', 'pointer');
    await close.focus();
    await expect(close).toBeFocused();
    await close.press('Enter');
    await sidebar.screenshot({ path: test.info().outputPath(`workflow-sidebar-${width}-${theme}.png`) });
  });
}

// contract-test: supporting surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
test('workflow sidebar empty state keeps the close control', async ({ page }) => {
  await page.goto(preview(325, 'empty'), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
  await expect(page.getByTestId('workflows-sidebar').getByText('No workflows yet.')).toBeVisible();
  await expect(page.getByTestId('workflow-sidebar-close')).toBeVisible();
});
