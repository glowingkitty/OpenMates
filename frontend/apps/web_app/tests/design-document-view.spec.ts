import type { Locator, Page } from '@playwright/test';
import { test, expect } from './helpers/cookie-audit';
import { createIsolatedBrowserContext, declareTestState } from './helpers/chat-test-helpers';
import { seedViaPairedCli, type Seed } from './helpers/owned-encrypted-embed-fixture';
import { getE2EDebugUrl } from './signup-flow-helpers';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- paired CLI fixture exports CommonJS.
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, runWorkflowCli, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

// Small synthetic PNG with a distinct center pixel to prove the actual asset painted.
const raster = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAUCAIAAABj86gYAAAAgklEQVR42mO0CMxgoCVgYqAxGLUADizTLGloAS7TqWMB3HSs1jCR7TQiFTDiyQfImo/POr5Z/RuagjZ7Z0xdx2cdJ8oHaE4j6FL6JVM0pzCRF7IU+YBy05FNYCHedKxRSpoPqBgycKOYaGE6nQo7iIuZaOp8qAW0M90yzZKJdqZDAADktxzLuWKdQgAAAABJRU5ErkJggg==';
const pageBounds = { width: 640, height: 480, background: '#f4e9d6' };
const scene = {
  schemaVersion: 1,
  title: 'Open Studio Weekend',
  pages: [
    { id: 'cover', name: 'Cover', ...pageBounds, layers: [
      { kind: 'text', id: 'headline', name: 'Headline', x: 48, y: 43, width: 544, height: 120, rotation: 0,
        text: 'Open Studio\nWeekend', font: 'Serif', fontSize: 48, weight: 700, color: '#18314b' },
      { kind: 'image', id: 'artwork', name: 'Studio artwork', x: 76, y: 171, width: 488, height: 210, rotation: 0 },
      { kind: 'text', id: 'date', name: 'Date', x: 48, y: 401, width: 540, height: 34, rotation: 0,
        text: 'Workshop and gallery · Saturday 11:00', font: 'Sans', fontSize: 22, weight: 400, color: '#18314b' }
    ] },
    { id: 'schedule', name: 'Schedule', ...pageBounds, layers: [
      { kind: 'shape', id: 'field', name: 'Panel', x: 40, y: 36, width: 560, height: 408, rotation: 0,
        shape: 'rectangle', color: '#18314b', radius: 18 },
      { kind: 'text', id: 'notes', name: 'Schedule', x: 80, y: 95, width: 470, height: 260, rotation: 0,
        text: 'Schedule\n\n11:00 Studio tour\n13:00 Print workshop\n15:00 Gallery talk', font: 'Serif', fontSize: 34,
        weight: 700, color: '#f4e9d6' }
    ] }
  ]
};

async function centerPixel(canvas: Locator): Promise<number[]> {
  return canvas.evaluate((node: HTMLCanvasElement) => {
    const { clientHeight, width, height } = node;
    const scale = Number(node.dataset.scale);
    // A remounted fullscreen may have painted before the host gives it a layout box.
    if (!clientHeight || !width || !height || !Number.isFinite(scale) || scale <= 0) return [];
    const y = ((clientHeight - 46 - 480 * scale) / 2 + 276 * scale) * height / clientHeight;
    return [...node.getContext('2d')!.getImageData(Math.floor(node.width / 2), Math.floor(y), 1, 1).data];
  });
}

const guestState = declareTestState({
  auth: 'signed-out guest', browserStorage: 'fresh', account: 'none',
  chat: 'private chat owned by the paired fixture account', notifications: 'none', securityReminders: 'none'
});

async function editHeadline(page: Page, headline: string) {
  await page.getByTestId('design-mode').click();
  await page.getByTestId('design-layer-headline').click();
  const text = page.getByTestId('design-property-text');
  await text.fill(headline);
  await text.press('Tab');
  await expect(text).toHaveValue(headline);
}

// contract-test: direct surface=gui.web assertions=design-editor.view.validated-scene,design-editor.view.client-side-encrypted,design-editor.edit.typed-layers,design-editor.edit.revision
test('views and edits a client-side encrypted Design, then reloads its revisions', async ({ page, browser }, info) => {
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
    'Uses the isolated API, WebSocket and paired CLI stack');
  const api = workflowApiUrl();
  const home = createWorkflowCliHome('design-view');
  let saved: Seed | undefined;
  try {
    await loginWorkflowCliViaPair(page, api, home, 'DESIGN_VIEW');
    await page.getByTestId('icon-button-close').click();
    saved = seedViaPairedCli(api, home, 'design', 0, false, { scene, raster });
    const route = getE2EDebugUrl(`/#chat-id=${saved.chatId}&embed-id=${saved.embedId}`);
    await page.goto(route, { waitUntil: 'domcontentloaded' });
    const canvas = page.getByTestId('design-canvas');
    await expect(canvas).toHaveAttribute('data-painted-page', 'cover', { timeout: 45_000 });
    await expect(canvas).toHaveAttribute('data-assets-ready', 'true', { timeout: 45_000 });
    await expect(canvas).not.toHaveAttribute('data-missing-assets', 'true');
    await expect.poll(() => centerPixel(canvas)).toEqual([235, 120, 94, 255]);
    await expect(page.getByTestId('design-workspace')).toHaveAttribute('data-mode', 'view');
    await page.getByTestId('design-page-chooser').click();
    await page.getByTestId('design-page-schedule').click();
    await expect(canvas).toHaveAttribute('data-painted-page', 'schedule');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(canvas).toHaveAttribute('data-painted-page', 'cover', { timeout: 45_000 });
    await expect(canvas).toHaveAttribute('data-assets-ready', 'true', { timeout: 45_000 });
    await expect.poll(() => centerPixel(canvas)).toEqual([235, 120, 94, 255]);
    const syncToast = page.getByTestId('notification').filter({ hasText: /Attempting to sync .* offline change/ });
    await expect(syncToast).toBeHidden({ timeout: 15_000 });
    const screenshot = info.outputPath('saved-design-after-reload.png');
    await page.getByTestId('design-fullscreen').screenshot({ path: screenshot, animations: 'disabled' });
    await info.attach('saved-design-after-reload', { path: screenshot, contentType: 'image/png' });

    const stale = await page.context().newPage();
    try {
      await stale.goto(route, { waitUntil: 'domcontentloaded' });
      await editHeadline(stale, 'Concurrent stale edit');
      await editHeadline(page, 'Open Studio Saturday');
      const x = page.getByTestId('design-property-x');
      await x.fill('62');
      await x.press('Tab');
      const width = page.getByTestId('design-property-width');
      await width.fill('518');
      await width.press('Tab');
      await expect(width).toHaveValue('518');
      await page.getByTestId('design-undo').click();
      await expect(width).toHaveValue('544');
      const [commit] = await Promise.all([
        page.waitForResponse(async (response) => {
          if (response.request().method() !== 'POST' ||
            !new URL(response.url()).pathname.endsWith('/user-revisions')) return false;
          // The first save may retry with the encrypted snapshot of the original version.
          return response.status() !== 409 || (await response.json()).detail !== 'base_snapshot_required';
        }, { timeout: 45_000 }),
        page.getByTestId('design-mode').click()
      ]);
      expect(commit.ok(), `Design revision request returned HTTP ${commit.status()}`).toBe(true);
      await expect(page.getByTestId('design-workspace')).toHaveAttribute('data-mode', 'view', { timeout: 40_000 });
      await expect(page.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });

      await stale.getByTestId('design-mode').click();
      await expect(stale.getByTestId('design-save-error')).toContainText('A newer version was saved', { timeout: 40_000 });
      await expect(stale.getByTestId('design-property-text')).toHaveValue('Concurrent stale edit');
    } finally {
      await stale.close();
    }

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(canvas).toHaveAttribute('data-assets-ready', 'true', { timeout: 45_000 });
    await page.getByTestId('version-dot-1').click();
    await expect(page.getByTestId('design-workspace')).toHaveAttribute('data-version', '1');
    await expect(page.getByTestId('design-mode')).toHaveCount(0);
    await page.getByTestId('version-dot-2').click();
    await page.getByTestId('design-mode').click();
    await page.getByTestId('design-layer-headline').click();
    await expect(page.getByTestId('design-property-text')).toHaveValue('Open Studio Saturday');
    await expect(page.getByTestId('design-property-x')).toHaveValue('62');
    await expect(page.getByTestId('design-property-width')).toHaveValue('544');
    await expect(syncToast).toBeHidden({ timeout: 15_000 });
    await info.attach('design-edit-after-reload', {
      body: await page.getByTestId('design-fullscreen').screenshot({ animations: 'disabled' }),
      contentType: 'image/png'
    });
    await page.getByTestId('design-mode').click();

    const guest = await createIsolatedBrowserContext(browser, guestState);
    try {
      const guestPage = await guest.newPage();
      await guestPage.goto(route, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      await expect(guestPage.getByTestId('login-email-input')).toBeVisible({ timeout: 30_000 });
      await expect(guestPage.getByTestId('design-canvas')).toHaveCount(0);
      await expect(guestPage.getByText(scene.title, { exact: true })).toHaveCount(0);
    } finally {
      await guest.close();
    }
  } finally {
    try {
      if (saved) {
        const deleted = await runWorkflowCli(api, home, ['chats', 'delete', saved.chatId, '--yes'], 30_000);
        expect(deleted.code, deleted.stderr).toBe(0);
      }
    } finally {
      removeWorkflowCliHome(home);
    }
  }
});
