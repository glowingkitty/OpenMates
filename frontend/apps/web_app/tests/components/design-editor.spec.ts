// playwright-account: not_required reason=isolated_component_preview
// contract-test-file: tooling
import type { Page, TestInfo } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const path = '/dev/preview/embeds/design/editor/DesignEditorFullscreen';
const board = (page: Page) => page.getByTestId('design-canvas');
const workspace = (page: Page) => page.getByTestId('design-workspace');

async function openDesign(page: Page, theme: 'light' | 'dark', width: number, variant = '', pageId = 'flyer') {
  const query = new URLSearchParams({ theme, width: String(width), background: '#dbeafe', chrome: '0', variant });
  await page.goto(`${path}?${query}`);
  await waitForComponentPreview(page);
  await expect(board(page)).toHaveAttribute('data-painted-page', pageId);
}

async function artPoint(page: Page, x: number, y: number, artWidth = 640, artHeight = 800) {
  const rect = (await board(page).boundingBox())!;
  const scale = Number(await board(page).getAttribute('data-scale'));
  return {
    x: rect.x + (rect.width - artWidth * scale) / 2 + x * scale,
    y: rect.y + (rect.height - 46 - artHeight * scale) / 2 + y * scale,
    scale
  };
}

async function drag(page: Page, start: { x: number; y: number }, dx: number, dy: number) {
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + dx, start.y + dy, { steps: 9 });
  await page.mouse.up();
}

async function expectGeometry(page: Page, label: string, target: number) {
  await expect.poll(async () => Math.abs(Number(await page.getByLabel(label, { exact: true }).inputValue()) - target)).toBeLessThan(2.1);
}

async function shot(page: Page, info: TestInfo, name: string) {
  const bounds = await page.getByRole('toolbar', { name: 'Design tools' }).boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
  const output = info.outputPath(`${name}.png`);
  await page.screenshot({ path: output, animations: 'disabled' });
  await info.attach(name, { path: output, contentType: 'image/png' });
}

test.describe('desktop design preview', () => {
  test.use({ viewport: { width: 1280, height: 860 }, reducedMotion: 'reduce' });

  test('reads and edits a flyer, then previews the revised artwork', async ({ page }, info) => {
    await openDesign(page, 'light', 1280);
    await expect(workspace(page)).toHaveAttribute('data-mode', 'view');
    await expect(page.getByRole('complementary', { name: 'Layers' })).toHaveCount(0);
    await shot(page, info, 'desktop-light-view');
    const edge = await artPoint(page, 8, 400);
    const opacity = () => board(page).evaluate((node: HTMLCanvasElement, point) => {
      const bounds = node.getBoundingClientRect();
      const x = (point.x - bounds.left) * node.width / bounds.width;
      const y = (point.y - bounds.top) * node.height / bounds.height;
      return node.getContext('2d')!.getImageData(x, y, 1, 1).data[3];
    }, edge);
    await expect.poll(opacity).toBe(255);
    await drag(page, edge, 60, 0);
    await expect.poll(opacity).toBeLessThan(70);
    await page.getByRole('button', { name: 'Reset zoom' }).click();

    await page.getByRole('button', { name: 'Edit design' }).click();
    await expect(page.getByRole('button', { name: 'View design' })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();
    const headline = await artPoint(page, 290, 180);
    await page.mouse.click(headline.x, headline.y);
    await expect(workspace(page)).toHaveAttribute('data-selection', 'headline');
    await expect(page.getByRole('textbox', { name: 'Text', exact: true })).toHaveValue('Afterlight');
    await shot(page, info, 'desktop-light-edit');

    await drag(page, headline, 12 * headline.scale, 20 * headline.scale);
    await expectGeometry(page, 'X', 71);
    await expectGeometry(page, 'Y', 152);
    const corner = await artPoint(page, 71 + 533, 152 + 123);
    await drag(page, corner, 20 * corner.scale, 30 * corner.scale);
    await expectGeometry(page, 'Width', 553);
    await expectGeometry(page, 'Height', 153);
    const handle = await artPoint(page, 71 + 553 / 2, 152);
    const radius = 29 + 153 * handle.scale / 2;
    await drag(page, { x: handle.x, y: handle.y - 29 }, radius, radius);
    await expectGeometry(page, 'Angle', 90);
    await page.getByRole('button', { name: 'Undo', exact: true }).click();
    await expect(page.getByLabel('Angle', { exact: true })).toHaveValue('0');

    const text = page.getByRole('textbox', { name: 'Text', exact: true });
    await text.fill('Afterglow');
    await text.press('Tab');
    await page.getByRole('button', { name: 'Set color #ff775c' }).click();
    await expect(page.getByLabel('Color', { exact: true })).toHaveValue('#ff775c');
    await page.getByRole('button', { name: 'Undo', exact: true }).click();
    await expect(page.getByLabel('Color', { exact: true })).toHaveValue('#fff0ce');
    await page.getByRole('button', { name: 'Redo', exact: true }).click();
    await expect(page.getByLabel('Color', { exact: true })).toHaveValue('#ff775c');

    const layer = page.getByTestId('design-layer-headline');
    const initialPosition = await page.locator('[data-testid^="design-layer-"]').evaluateAll((items) =>
      items.findIndex((item) => item.getAttribute('data-testid') === 'design-layer-headline'));
    await page.getByRole('button', { name: 'Bring forward' }).click();
    await expect(page.locator('[data-testid^="design-layer-"]').nth(initialPosition - 1)).toHaveAttribute('data-testid', 'design-layer-headline');
    await page.getByRole('button', { name: 'Hide layer' }).click();
    await expect(page.getByRole('button', { name: 'Show layer' })).toBeVisible();
    await page.getByRole('button', { name: 'Show layer' }).click();
    await page.getByRole('button', { name: 'Lock layer', exact: true }).click();
    await expect(page.getByText('Unlock this layer to edit it.')).toBeVisible();
    await page.getByRole('button', { name: 'Unlock layer', exact: true }).click();
    await layer.focus();
    await page.keyboard.press('ControlOrMeta+c');
    await page.keyboard.press('ControlOrMeta+v');
    await expect(workspace(page)).toHaveAttribute('data-layers', '11');
    await page.keyboard.press('ControlOrMeta+z');
    await expect(workspace(page)).toHaveAttribute('data-layers', '10');
    await expect(text).toHaveValue('Afterglow');

    await page.getByTestId('design-mode').click();
    await expect(workspace(page)).toHaveAttribute('data-mode', 'view');
    await expect(page.getByRole('complementary', { name: 'Properties' })).toHaveCount(0);
  });

  test('renders the image, vector and multi-page fixtures', async ({ page }, info) => {
    await openDesign(page, 'dark', 1280, 'collage', 'collage');
    await expect(board(page)).toHaveAccessibleName('Collage, 800 by 630, 7 layers');
    await shot(page, info, 'desktop-dark-collage');
    await openDesign(page, 'light', 1280, 'social-post', 'post');
    await shot(page, info, 'desktop-light-social-post');
    await openDesign(page, 'dark', 1280, 'app-mockup', 'explore');
    await page.getByRole('button', { name: /Explore 1/ }).click();
    await expect(page.locator('#design-pages canvas')).toHaveCount(3);
    await shot(page, info, 'desktop-dark-page-chooser');
    await page.getByRole('button', { name: 'Saved', exact: true }).click();
    await expect(board(page)).toHaveCount(1);
    await expect(board(page)).toHaveAttribute('data-painted-page', 'saved');
    await page.getByRole('button', { name: /Saved 2/ }).click();
    await page.getByRole('button', { name: 'Profile', exact: true }).click();
    await expect(board(page)).toHaveAttribute('data-painted-page', 'profile');
    await openDesign(page, 'light', 1280, 'stress-1000', 'stress');
    await expect(workspace(page)).toHaveAttribute('data-layers', '1000');
    await expect(page.locator('[data-testid^="design-layer-"]')).toHaveCount(40);
    await shot(page, info, 'desktop-light-stress');
  });
});

test.describe('phone design preview', () => {
  test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });

  test('pinches in view mode and edits through mobile panels', async ({ page }, info) => {
    await openDesign(page, 'dark', 390);
    await shot(page, info, 'phone-dark-view');
    const bounds = (await board(page).boundingBox())!;
    const client = await page.context().newCDPSession(page);
    const x = Math.round(bounds.x + bounds.width / 2);
    const y = Math.round(bounds.y + bounds.height / 2);
    const scale = Number(await board(page).getAttribute('data-scale'));
    await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x - 40, y, id: 1 }, { x: x + 40, y, id: 2 }] });
    await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 75, y, id: 1 }, { x: x + 75, y, id: 2 }] });
    await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect.poll(async () => Number(await board(page).getAttribute('data-scale'))).toBeGreaterThan(scale * 1.5);
    await client.detach();
    await page.getByRole('button', { name: 'Reset zoom' }).tap();

    await page.getByTestId('design-mode').tap();
    await page.getByRole('button', { name: 'Layers', exact: true }).tap();
    await page.getByTestId('design-layer-headline').tap();
    await expect(workspace(page)).toHaveAttribute('data-selection', 'headline');
    await shot(page, info, 'phone-dark-layers');
    await page.getByRole('button', { name: 'Properties', exact: true }).tap();
    await expect(page.getByRole('complementary', { name: 'Layers' })).toBeHidden();
    const font = page.getByLabel('Font', { exact: true });
    await font.selectOption('Sans');
    await expect(font).toHaveValue('Sans');
    await shot(page, info, 'phone-dark-edit');
    await page.getByRole('button', { name: 'Close properties' }).tap();
    await expect(page.getByRole('complementary', { name: 'Properties' })).toBeHidden();
    await page.getByTestId('design-mode').tap();
    await expect(workspace(page)).toHaveAttribute('data-mode', 'view');

    await openDesign(page, 'light', 390, 'social-post', 'post');
    await shot(page, info, 'phone-light-social-post');
  });
});
