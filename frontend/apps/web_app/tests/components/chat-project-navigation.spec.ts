// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers use CommonJS. */
export {};
import { waitForComponentPreview } from '../helpers/component-preview';
const { test, expect } = require('../helpers/cookie-audit');
const preview = (component: string, width: number, variant?: string) =>
  `/dev/preview/chats/${component}?${new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', ...(variant ? { variant } : {}) })}`;

for (const width of [280, 325]) {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable,chat-navigation.activity.global-running
  test(`nested chat navigation stays flat and readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(preview('ChatProjectNavigator', width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const navigator = page.getByTestId('chat-project-navigation');
    await expect(navigator).toBeVisible();
    await expect(navigator.getByRole('button', { name: 'Website launch' })).toBeVisible();
    await expect(navigator.getByTestId('chat-processing-wheel')).toHaveCount(1);
    await navigator.getByRole('button', { name: 'Website launch' }).click();
    await expect(navigator.getByRole('navigation')).toContainText('Website launch');
    await expect(navigator.getByRole('button', { name: 'Show full path' })).toHaveCount(0);
    const row = navigator.getByTestId('chat-project-folder');
    const rootGeometry = await row.boundingBox();
    await row.click(); // Marketing: a direct child has no middle overflow.
    await expect(navigator.getByRole('navigation')).toContainText('Marketing');
    await expect(navigator.getByRole('button', { name: 'Show full path' })).toHaveCount(0);
    await row.click(); // Campaigns
    await row.click(); // Launch copy
    await expect(navigator.getByRole('navigation')).toContainText('Launch copy');
    await expect(row).toContainText('Drafts');
    await expect(row.getByTestId('chat-processing-wheel')).toBeVisible();
    const deepGeometry = await row.boundingBox();
    expect(deepGeometry!.x).toBe(rootGeometry!.x);
    expect(deepGeometry!.width).toBe(rootGeometry!.width);
    const overflow = navigator.getByRole('button', { name: 'Show full path' });
    await overflow.focus(); await overflow.press('Enter');
    const ancestors = navigator.getByTestId('chat-project-ancestors');
    await expect(ancestors.getByRole('button')).toHaveText(['Website launch', 'Marketing', 'Campaigns', 'Launch copy']);
    await ancestors.getByRole('button', { name: 'Marketing', exact: true }).click();
    await expect(ancestors).toHaveCount(0);
    await expect(navigator.getByRole('navigation')).toContainText('Marketing');
    const bounds = await navigator.evaluate((element: HTMLElement) => ({ width: element.clientWidth, scroll: element.scrollWidth }));
    expect(bounds.scroll).toBeLessThanOrEqual(bounds.width + 1);
    await navigator.screenshot({ path: test.info().outputPath(`nested-project-${width}.png`) });
  });
}

// contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
test('project picker selects a deep destination and retains a failed selection', async ({ page }) => {
  await page.setViewportSize({ width: 325, height: 844 });
  await page.addInitScript(() => {
    window.addEventListener('preview-project-selected', event => {
      (window as Window & { selectedProject?: unknown }).selectedProject = (event as CustomEvent).detail;
    });
  });
  await page.goto(preview('ChatProjectPicker', 325), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  const dialog = page.getByTestId('chat-project-picker');
  await expect(dialog).toBeVisible();
  await dialog.getByTestId('chat-project-root').click();
  await dialog.getByTestId('chat-project-folder').click();
  await dialog.getByTestId('chat-project-folder').click();
  await dialog.getByTestId('chat-project-add-here').click();
  await expect(dialog).toHaveCount(0);
  expect(await page.evaluate(() => (window as Window & { selectedProject?: unknown }).selectedProject)).toEqual({ projectId: 'launch', folderId: 'campaigns' });
  await page.goto(preview('ChatProjectPicker', 325, 'error'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await dialog.getByTestId('chat-project-root').click();
  await dialog.getByTestId('chat-project-add-here').click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByRole('navigation')).toContainText('Website launch');
  await expect(dialog.getByTestId('chat-project-add-here')).toBeEnabled();
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
test('activity count reveals the sidebar and respects reduced motion', async ({ page }) => {
  await page.goto(preview('ActiveChatsLink', 280, 'single'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  const link = page.getByTestId('active-chats-link');
  await expect(link).toHaveText('1 chat active…');
  await page.evaluate(() => {
    window.addEventListener('openmates-reveal-running-chats', () => { (window as Window & { revealed?: boolean }).revealed = true; });
  });
  await link.focus(); await link.press('Enter');
  expect(await page.evaluate(() => (window as Window & { revealed?: boolean }).revealed)).toBe(true);
  await page.goto(preview('ActiveChatsLink', 280, 'empty'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true');
  await expect(link).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(preview('ProcessingWheel', 280), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-processing-wheel')).toHaveCSS('animation-name', 'none');
});

// contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
test('production chat row replaces its icon while processing and restores it on completion', async ({ page }) => {
  await page.goto(preview('ChatActivityPreview', 280), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  const row = page.getByTestId('chat-item-wrapper');
  await expect(row).toContainText('Launch copy');
  await expect(row.getByTestId('chat-processing-wheel')).toBeVisible();
  await expect(row.locator('.category-circle')).toHaveCount(0);
  await page.getByTestId('preview-complete-chat').click();
  await expect(row.getByTestId('chat-processing-wheel')).toHaveCount(0);
  await expect(row.locator('.category-circle')).toBeVisible();
});
