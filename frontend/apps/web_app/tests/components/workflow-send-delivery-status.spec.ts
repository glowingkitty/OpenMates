// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

async function openDelivery(page: Page, variant: string, width = 900): Promise<void> {
  await page.setViewportSize({ width, height: page.viewportSize()?.height ?? 900 });
  const query = new URLSearchParams({ variant, theme: 'light', background: '#dbeafe', width: String(width), chrome: '0' });
  await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${query}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="send"]')).toBeVisible();
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
}

test.describe('Workflow Send delivery status preview', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
  test('keeps pending and claimed delivery waiting with no premature chat link', async ({ page }: { page: Page }) => {
    for (const variant of ['deliveryMissingStatus', 'deliveryPending', 'deliveryClaimed']) {
      await openDelivery(page, variant);
      const send = page.locator('[data-testid="workflow-node-card"][data-node-id="send"]');
      await expect(send.getByTestId('workflow-run-node-status')).toHaveAttribute('aria-label', 'Waiting');
      await expect(send.getByTestId('workflow-run-node-status')).not.toHaveClass(/success/);
      await expect(send.getByRole('link', { name: 'Open chat' })).toHaveCount(0);
      await send.getByTestId('workflow-node-summary').click();
      await expect(send.getByTestId('workflow-node-expanded')).toBeVisible();
      await expect(send.getByRole('link', { name: 'Open chat' })).toHaveCount(0);
    }
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
  test('shows the delivered chat link and failure distinctly at laptop and phone widths', async ({ page }: { page: Page }) => {
    for (const width of [900, 390]) {
      await openDelivery(page, 'deliveryAcknowledged', width);
      const send = page.locator('[data-testid="workflow-node-card"][data-node-id="send"]');
      await expect(send.getByTestId('workflow-run-node-status')).toHaveAttribute('data-node-status', 'acknowledged');
      await expect(send.getByTestId('workflow-run-node-status')).toHaveClass(/success/);
      await expect(send.getByTestId('workflow-run-open-chat')).toHaveAttribute('href', '/#chat-id=preview-delivered-chat');
      await expect(send.getByTestId('workflow-run-open-chat')).toBeVisible();
      const bounds = await send.getByTestId('workflow-run-open-chat').boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      await send.getByTestId('workflow-node-summary').click();
      await expect(send.getByTestId('workflow-node-expanded').getByRole('link', { name: 'Open chat' })).toBeVisible();
    }
    await openDelivery(page, 'deliveryExpired');
    const failed = page.locator('[data-testid="workflow-node-card"][data-node-id="send"]');
    await expect(failed.getByTestId('workflow-run-node-status')).toHaveAttribute('aria-label', 'Failed');
    await expect(failed.getByRole('link', { name: 'Open chat' })).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
  test('does not leave unverified or stale nodes waiting after a terminal run', async ({ page }: { page: Page }) => {
    await openDelivery(page, 'deliveryNoEvidence');
    await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="send"] [data-testid="workflow-run-node-status"]')).toHaveAttribute('aria-label', 'Failed');

    await openDelivery(page, 'deliveryTerminalStale');
    await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="trigger"] [data-testid="workflow-run-node-status"]')).toHaveAttribute('aria-label', 'Failed');
    await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="send"] [data-testid="workflow-run-node-status"]')).toHaveAttribute('aria-label', 'Waiting');
  });
});
