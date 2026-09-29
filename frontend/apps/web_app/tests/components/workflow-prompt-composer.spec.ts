// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

const preview = (width: number, variant?: string) =>
  `/dev/preview/workspace/WorkspacePromptComposer?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

test.describe('Workflow prompt composer', () => {
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
