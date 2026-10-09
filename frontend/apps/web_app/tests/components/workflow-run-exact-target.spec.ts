// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

async function openRunHistory(page: Page, width: number, variant?: string): Promise<void> {
  await page.setViewportSize({ width, height: 800 });
  await page.route('**/v1/workflows/preview-workflow*', route => {
    const path = new URL(route.request().url()).pathname;
    const runs = ['latest-run', 'older-run'].map((id, index) => ({
      id, workflow_id: 'preview-workflow', version_id: 'preview-version', status: 'completed',
      trigger_type: 'manual', started_at: index === 0 ? 1_760_000_000 : 1_750_000_000,
    }));
    const graph = { version: 2, trigger_node_id: 'trigger', nodes: [{ id: 'trigger', type: 'manual_trigger', config: {} }], edges: [] };
    const body = path.endsWith('/runs') ? { runs }
      : path.endsWith('/runs/older-run') ? { run: { ...runs[1], node_runs: [], output_summary: {}, content_available: false } }
      : { workflow: { id: 'preview-workflow', title: 'Weekly report', enabled: false, status: 'active', current_version_id: 'preview-version', graph } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  const params = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', ...(variant ? { variant } : {}) });
  await page.goto(`/dev/preview/workflows/WorkflowRunHistory?${params}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 60_000);
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
}

test.describe('Workflow exact run history target preview', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.workflow-run.run-target
  test('selects the older requested run and keeps a missing ID unavailable at phone and laptop widths', async ({ page }: { page: Page }) => {
    test.setTimeout(90_000);
    for (const width of [390, 900]) {
      await openRunHistory(page, width);
      const older = page.locator('[data-testid="workflow-run-marker"][data-run-id="older-run"]');
      const latest = page.locator('[data-testid="workflow-run-marker"][data-run-id="latest-run"]');
      await expect(older).toHaveAttribute('aria-pressed', 'true');
      await expect(latest).toHaveAttribute('aria-pressed', 'false');
      await expect(page.getByTestId('workflow-run-unavailable')).toHaveCount(0);

      await openRunHistory(page, width, 'missing');
      await expect(page.getByTestId('workflow-run-unavailable')).toBeVisible();
      await expect(page.getByTestId('workflow-run-unavailable')).toHaveAttribute('role', 'alert');
      await expect(page.locator('[data-testid="workflow-run-marker"][aria-pressed="true"]')).toHaveCount(0);
      const bounds = await page.getByTestId('workflow-run-unavailable').boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    }
  });
});
