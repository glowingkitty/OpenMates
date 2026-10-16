// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page, Route } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

async function preview(page: Page, variant: string, width = 900): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${new URLSearchParams({ variant, theme: 'light', width: String(width), chrome: '0' })}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await page.locator('[data-node-id="trigger"]').getByTestId('workflow-node-summary').click();
}

async function repeat(page: Page, name: string): Promise<void> {
  await page.getByTestId('workflow-time-trigger-schedule').selectOption({ label: name });
}

test.describe('Recurring Workflow start', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.schedule.preview
  test('reopens an offset-authored start in the selected timezone and preserves its instant', async ({ page }: { page: Page }) => {
    let saved: { nodes: Array<{ id: string; config: { schedule: Record<string, unknown> } }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      saved = route.request().postDataJSON().graph;
      await route.fulfill({ json: {} });
    });
    await page.goto('/dev/preview/workflows/WorkflowGraphRenderer?variant=scheduleStartOffset&theme=light&width=900&chrome=0', { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.locator('[data-node-id="trigger"]').getByTestId('workflow-node-summary')).toContainText('Starts 2026-11-02 14:30 Europe/Berlin');
    await page.locator('[data-node-id="trigger"]').getByTestId('workflow-node-summary').click();
    const start = page.getByTestId('workflow-time-trigger-start');
    await expect(start).toHaveValue('2026-11-02T14:30');
    await expect(page.getByTestId('workflow-node-expanded')).toContainText('Start on (optional)');
    await repeat(page, 'Every week');
    await expect(start).toHaveValue('2026-11-02T14:30');
    await repeat(page, 'Every hour');
    await expect(start).toHaveValue('2026-11-02T14:30');
    await page.getByTestId('workflow-node-expanded').getByRole('textbox', { name: 'Timezone' }).fill('America/New_York');
    await expect(start).toHaveValue('2026-11-02T08:30');
    await page.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes.find(node => node.id === 'trigger')?.config.schedule).toMatchObject({ type: 'hourly', timezone: 'America/New_York', starts_at: '2026-11-02T08:30:00-05:00' });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.schedule.preview
  test('adds and clears a recurring start, then removes it when switching to once', async ({ page }: { page: Page }) => {
    let saved: { nodes: Array<{ id: string; config: { schedule: Record<string, unknown> } }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      saved = route.request().postDataJSON().graph;
      await route.fulfill({ json: {} });
    });
    await preview(page, 'scheduleStartEmpty', 390);
    const start = page.getByTestId('workflow-time-trigger-start');
    await expect(start).toBeVisible();
    await start.focus();
    await expect(start).toBeFocused();
    // Native date/time inputs tab through their internal segments before the next field.
    for (let index = 0; index < 8; index++) {
      await page.keyboard.press('Tab');
      if (!await start.evaluate(element => element === document.activeElement)) break;
    }
    await expect(start).not.toBeFocused();
    const startBox = await start.boundingBox();
    expect(startBox!.x).toBeGreaterThanOrEqual(0);
    expect(startBox!.x + startBox!.width).toBeLessThanOrEqual(390);
    await start.fill('2026-11-02T10:15');
    await repeat(page, 'Every day');
    await expect(start).toHaveValue('2026-11-02T10:15');
    await page.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes.find(node => node.id === 'trigger')?.config.schedule).toMatchObject({ type: 'daily', starts_at: '2026-11-02T09:15:00.000Z' });
    await preview(page, 'scheduleStartOffset', 390);
    await page.getByTestId('workflow-time-trigger-start').fill('');
    await page.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes.find(node => node.id === 'trigger')?.config.schedule).not.toHaveProperty('starts_at');
    await preview(page, 'scheduleStartOffset', 390);
    await repeat(page, 'Once');
    await expect(page.getByTestId('workflow-time-trigger-start')).toHaveCount(0);
    await expect(page.getByTestId('workflow-time-trigger-at')).toBeVisible();
    await page.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes.find(node => node.id === 'trigger')?.config.schedule).not.toHaveProperty('starts_at');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.schedule.preview
  test('shows the once value in the schedule timezone', async ({ page }: { page: Page }) => {
    await preview(page, 'scheduleOnceOffset');
    await expect(page.getByTestId('workflow-time-trigger-at')).toHaveValue('2026-11-02T14:30');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.schedule.preview
  test('normalizes a legacy local start before changing timezone', async ({ page }: { page: Page }) => {
    let saved: { nodes: Array<{ config: { schedule: Record<string, unknown> } }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      saved = route.request().postDataJSON().graph;
      await route.fulfill({ json: {} });
    });
    await preview(page, 'scheduleStartNaive');
    const start = page.getByTestId('workflow-time-trigger-start');
    await expect(start).toHaveValue('2026-10-18T00:00');
    await page.getByTestId('workflow-node-expanded').getByRole('textbox', { name: 'Timezone' }).fill('UTC');
    await expect(start).toHaveValue('2026-10-17T22:00');
    await page.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes[0].config.schedule).toMatchObject({ timezone: 'UTC', starts_at: '2026-10-18T00:00:00+02:00' });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.schedule.preview
  test('rejects a nonexistent daylight saving wall time visibly', async ({ page }: { page: Page }) => {
    await preview(page, 'scheduleStartOffset');
    const start = page.getByTestId('workflow-time-trigger-start');
    await start.fill('2026-03-29T02:30');
    await expect(page.getByRole('alert')).toHaveText('Choose a valid date and time in this timezone.');
    await expect(start).toHaveValue('2026-11-02T14:30');
  });
});
