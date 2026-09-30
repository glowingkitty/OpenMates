// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

const preview = (width: number, variant?: string, theme = 'light') =>
  `/dev/preview/workspace/WorkspacePromptComposer?${new URLSearchParams({
    theme, background: '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

test.describe('Workflow prompt composer', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.composer-drop-import,workflows-ui.responsive-accessible-reachable
  test('file import replaces the AI icon, matches the microphone and fits phone and laptop inputs', async ({ page }: { page: Page }) => {
    for (const width of [390, 1280]) {
      for (const theme of ['light', 'dark']) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(preview(width, undefined, theme), { waitUntil: 'networkidle' });
        const composer = page.getByTestId('workflows-input-composer');
        const input = page.getByTestId('workflows-input-textarea');
        const file = composer.getByRole('button', { name: 'Import .workflow.yml', exact: true });
        const mic = page.getByTestId('workflows-input-mic');
        await expect(input).toHaveAttribute('placeholder', 'Describe new workflow.');
        await expect(file).toBeVisible();
        await expect(mic).toBeVisible();
        await expect(composer.locator('.workspace-prompt-ai-icon')).toHaveCount(0);
        const icon = file.locator('.icon_files');
        const gradient = await icon.evaluate((element) => getComputedStyle(element).backgroundImage);
        expect(gradient).toContain('linear-gradient');
        await expect(mic).toHaveCSS('background-image', gradient);
        // Vite may inline the SVG into a data URL; the icon must still have a mask.
        expect(await icon.evaluate((element) => getComputedStyle(element).maskImage)).not.toBe('none');
        const [fileBox, inputBox, micBox] = await Promise.all([file.boundingBox(), input.boundingBox(), mic.boundingBox()]);
        if (!fileBox || !inputBox || !micBox) throw new Error('Composer controls must be measurable.');
        expect(fileBox.width).toBeGreaterThanOrEqual(36);
        expect(fileBox.width).toBeLessThanOrEqual(44);
        expect(fileBox.x).toBeGreaterThanOrEqual(0);
        expect(fileBox.x + fileBox.width).toBeLessThanOrEqual(inputBox.x + 1);
        expect(inputBox.x + inputBox.width).toBeLessThanOrEqual(micBox.x + 1);
        expect(micBox.x + micBox.width).toBeLessThanOrEqual(width);
        await file.focus();
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await expect(file).toBeFocused();
        await expect(file).toHaveCSS('outline-style', 'solid');
        await file.hover();
        await file.click();
        await input.fill('Every morning, send me the weather');
        await expect(file).toBeVisible();
        await expect(page.getByTestId('workflows-input-submit')).toBeVisible();
        const [filledFileBox, filledInputBox] = await Promise.all([file.boundingBox(), input.boundingBox()]);
        if (!filledFileBox || !filledInputBox) throw new Error('Filled composer controls must be measurable.');
        expect(filledFileBox.x + filledFileBox.width).toBeLessThanOrEqual(filledInputBox.x + 2);
      }
    }
    await page.goto(preview(390, 'disabled'), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-import-button')).toBeDisabled();
    await page.goto(preview(390, 'projects'), { waitUntil: 'networkidle' });
    await expect(page.locator('.workspace-prompt-ai-icon')).toBeVisible();
    await expect(page.getByTestId('workflow-import-button')).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
  test('Safari edge backgrounds remain opaque and follow light and dark theme changes', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => localStorage.setItem('theme_mode', 'dark'));
    for (const theme of ['dark', 'light', 'dark']) {
      await page.goto(preview(390, undefined, theme), { waitUntil: 'networkidle' });
      const rgb = theme === 'dark' ? 'rgb(23, 23, 23)' : 'rgb(255, 255, 255)';
      const hex = theme === 'dark' ? '#171717' : '#ffffff';
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('html')).toHaveCSS('background-color', rgb);
      await expect(page.locator('body')).toHaveCSS('background-color', rgb);
      await expect(page.locator('html')).toHaveCSS('color-scheme', theme);
      await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', hex);
      for (const edge of ['top', 'bottom']) {
        const sampler = page.locator(`.safari-browser-tint-sampler.${edge}`);
        await expect(sampler).toHaveCSS('background-color', rgb);
        await expect(sampler).toHaveCSS('position', 'fixed');
        await expect(sampler).toHaveCSS('pointer-events', 'none');
        const box = await sampler.boundingBox();
        if (!box) throw new Error('Safari edge background must be measurable.');
        expect(box.height).toBeGreaterThan(10);
        expect(box.width).toBeGreaterThanOrEqual(390);
        expect(edge === 'top' ? box.y : box.y + box.height).toBe(edge === 'top' ? 0 : 844);
      }
    }
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('.safari-browser-tint-sampler.top')).toHaveCSS('background-color', 'rgb(23, 23, 23)');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
  test('fits the shared recording overlay inside the phone composer', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview(390, 'recording'), { waitUntil: 'networkidle' });
    const composer = page.getByTestId('workflows-input-composer');
    const recorder = page.getByTestId('record-overlay');
    await expect(composer).toBeVisible();
    await expect(recorder).toBeVisible();
    await expect(page.getByTestId('record-finish-button')).toBeVisible();
    await expect(page.getByTestId('record-cancel-button')).toBeVisible();
    const composerBox = await composer.boundingBox();
    const recorderBox = await recorder.boundingBox();
    if (!composerBox || !recorderBox) throw new Error('Recording layout must be measurable.');
    expect(composerBox.height).toBeGreaterThanOrEqual(220);
    expect(recorderBox.y).toBeGreaterThanOrEqual(composerBox.y - 1);
    expect(recorderBox.y + recorderBox.height).toBeLessThanOrEqual(composerBox.y + composerBox.height + 1);
    expect(recorderBox.x).toBeGreaterThanOrEqual(0);
    expect(recorderBox.x + recorderBox.width).toBeLessThanOrEqual(391);
  });
});
