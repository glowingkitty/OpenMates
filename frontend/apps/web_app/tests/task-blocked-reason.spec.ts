/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Blocked Task detail component coverage for encrypted human explanations and
 * safe reason-code fallbacks. The deterministic preview avoids API plaintext
 * fixtures while proving the deployed responsive presentation.
 *
 * Plan: docs/plans/opencode-external-task-bridge/plan.yml
 */
export {};

import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const TASK_BLOCKED_REASON_PROOF = defineVideoProof({
  id: 'task-blocked-reason',
  title: 'Blocked Task explanation and fallback',
  surface: 'web',
  devices: ['web-laptop', 'web-phone'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'encrypted-explanation', text: 'The blocked Task shows the decrypted private explanation in the detail view without clipping the long text.', checkpoint: 'encrypted-explanation', devices: ['web-laptop', 'web-phone'] },
    { id: 'code-fallback', text: 'When no private explanation exists, the Task detail displays the localized safe fallback for its blocked reason code.', checkpoint: 'code-fallback', devices: ['web-laptop', 'web-phone'] },
  ],
  assertions: [
    { id: 'explanation-readable', checkpoint: 'encrypted-explanation', visual: 'The complete long explanation is readable and does not overflow the viewport.', devices: ['web-laptop', 'web-phone'] },
    { id: 'fallback-readable', checkpoint: 'code-fallback', visual: 'The localized code fallback is visible without fabricated private text or horizontal overflow.', devices: ['web-laptop', 'web-phone'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

async function openPreview(page: Page, variant?: string): Promise<void> {
  const query = variant ? `&variant=${encodeURIComponent(variant)}` : '';
  const response = await page.goto(`/dev/preview/tasks/TaskDetailFullscreen?chrome=0${query}`, { waitUntil: 'networkidle' });
  expect(response?.status()).toBe(200);
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 15_000 });
  await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
}

async function expectNoOverflow(page: Page, targetTestId: string): Promise<void> {
  const measurements = await page.getByTestId(targetTestId).evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(measurements.scrollWidth, `${targetTestId} should not clip or overflow`).toBeLessThanOrEqual(measurements.clientWidth + 1);
  const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(pageOverflow, 'Task detail should not create horizontal page overflow').toBeLessThan(8);
}

test.describe('Task blocked reason component', () => {
  // contract-test: direct surface=gui.web assertions=tasks.blocking.encrypted-reason,tasks.lifecycle.visible,tasks.surface.semantic-parity
  test('renders the decrypted explanation and localized code fallback without clipping', async ({ page }: { page: Page }, testInfo: TestInfo) => {
    const proof = createVideoProofRuntime(TASK_BLOCKED_REASON_PROOF, {
      device: PROOF_DEVICE,
      attach: testInfo.attach.bind(testInfo),
      captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await openPreview(page);

    const detail = page.getByTestId('task-detail-content');
    const reason = detail.getByTestId('task-detail-blocked-reason');
    await expect(reason).toContainText('credential must be created with repository write access');
    await proof.assert('explanation-readable', async () => {
      await expect(reason).toBeVisible();
      await expectNoOverflow(page, 'task-detail-blocked-reason');
    });
    await proof.checkpoint('encrypted-explanation');

    await proof.action('show-code-fallback', async () => openPreview(page, 'codeFallback'));
    const fallbackReason = page.getByTestId('task-detail-blocked-reason');
    await expect(fallbackReason).toContainText('Credentials are required before this Task can continue.');
    await expect(fallbackReason).not.toContainText('repository write access');
    await proof.assert('fallback-readable', async () => {
      await expect(fallbackReason).toBeVisible();
      await expectNoOverflow(page, 'task-detail-blocked-reason');
    });
    await proof.checkpoint('code-fallback');
    await proof.attach();
  });
});
