// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const codeIds = ['91000000-0000-4000-8000-000000000001', '91000000-0000-4000-8000-000000000002'];
const searchId = '91000000-0000-4000-8000-000000000003';
const preview = (component: string, width: number, variant?: string) =>
  `/dev/preview/${component}?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}) })}`;

for (const width of [1366, 390]) {
  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,settings-ui.shell.lifecycle-and-routing
  test(`app embeds open, close and reopen the selected viewer without a chat host at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(preview('settings/appSettings/AppEmbedsPanel', width));
    await waitForComponentPreview(page);
    const url = page.url();
    for (const [index, id] of codeIds.entries()) {
      const card = page.getByTestId(`app-embed-${id}`).getByTestId('embed-preview');
      await expect(card).toBeVisible();
      await card.getByTestId('result-preview-expand').click();
      const viewer = page.getByTestId('standalone-embed-fullscreen');
      await expect(viewer).toBeVisible();
      await expect(viewer).toContainText(`Library ${index + 1}.py`);
      await expect(viewer).toContainText(`library_value = ${42 + index}`);
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', {
        detail: { chat: { chat_id: 'background-chat' } },
      })));
      await expect(viewer).toBeVisible();
      await expect(viewer).toContainText(`library_value = ${42 + index}`);
      await expect(page.getByTestId('active-chat-container')).toHaveCount(0);
      const bounds = await viewer.boundingBox();
      expect(bounds?.width).toBe(width);
      expect(page.url()).toBe(url);
      await viewer.getByTestId('embed-minimize').click();
      await expect(viewer).toHaveCount(0);
      await expect(card).toBeVisible();
      expect(page.url()).toBe(url);
    }
  });
}

// contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen
test('the library viewer retains the original search graph and supports Escape', async ({ page }) => {
  await page.goto(preview('settings/appSettings/AppEmbedsPanel', 1366, 'search'));
  await waitForComponentPreview(page);
  await page.getByTestId(`app-embed-${searchId}`).getByTestId('embed-preview').click();
  const viewer = page.getByTestId('standalone-embed-fullscreen');
  await expect(viewer.getByTestId('embed-header-title')).toContainText('Library search');
  await expect(viewer).toContainText('Original library result');
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', {
    detail: { chat: { chat_id: 'background-chat' } },
  })));
  await expect(viewer).toContainText('Original library result');
  await page.keyboard.press('Escape');
  await expect(viewer).toHaveCount(0);
  await expect(page.getByTestId('app-embeds-panel')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen
test('standalone fullscreen uses the registered viewer in a bare preview', async ({ page }) => {
  await page.goto(preview('embeds/StandaloneEmbedFullscreen', 1366));
  await waitForComponentPreview(page);
  const viewer = page.getByTestId('standalone-embed-fullscreen');
  await expect(viewer).toBeVisible();
  await expect(viewer).toContainText('library_value = 42');
});
