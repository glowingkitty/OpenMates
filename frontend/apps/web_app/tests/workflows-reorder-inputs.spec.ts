/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser test helpers. */
export {};
import type { Page } from '@playwright/test';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost'
    ? 'http://localhost:8000'
    : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.actions.skill-contract
test('reorders persisted nodes and renders real fitness and travel date and location controls', async ({ page }: { page: Page }) => {
  test.setTimeout(180000);
  test.skip(!getTestAccount().email, 'Test account credentials required.');
  await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  await loginToTestAccount(page, () => {}, async () => {});

  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  const later = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10);
  const graph = {
    version: 2,
    trigger_node_id: 'trigger',
    nodes: [
      { id: 'trigger', type: 'schedule_trigger', config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } } },
      { id: 'fitness', type: 'app_skill_action', config: { app_id: 'fitness', skill_id: 'search_classes', input: { requests: [{ query: 'Yoga', city: 'Berlin', start_date: tomorrow, end_date: later }] } } },
      { id: 'stays', type: 'app_skill_action', config: { app_id: 'travel', skill_id: 'search_stays', input: { requests: [{ query: 'Hotels in Paris', check_in_date: tomorrow, check_out_date: later }] } } },
    ],
    edges: [{ from: 'trigger', to: 'fitness' }, { from: 'fitness', to: 'stays' }],
  };
  const created = await page.request.post(`${apiUrl()}/v1/workflows`, {
    data: { title: `Workflow reorder controls ${Date.now()}`, graph, enabled: false },
  });
  expect(created.ok()).toBe(true);
  const { workflow } = await created.json();
  try {
    await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workflow-landing-card').filter({ hasText: workflow.title }).first().click();
    const fitness = page.locator('[data-node-id="fitness"]');
    const stays = page.locator('[data-node-id="stays"]');

    await fitness.getByTestId('workflow-node-summary').click();
    await expect(fitness.getByTestId('workflow-node-move-up')).toHaveCount(0);
    await expect(fitness.getByTestId('workflow-node-move-down')).toBeVisible();
    await expect(fitness.getByTestId('workflow-schema-field-city').getByTestId('workflow-node-location-picker')).toBeVisible();
    await expect(fitness.getByTestId('workflow-schema-field-date-range')).toBeVisible();
    await expect(fitness.locator('input[id$="start_date"], input[id$="end_date"]')).toHaveCount(0);
    await fitness.getByTestId('workflow-date-range-specific').click();
    await expect(fitness.getByTestId('workflow-date-range-control')).toBeVisible();

    const movedByButton = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
    await fitness.getByTestId('workflow-node-move-down').click();
    expect((await movedByButton).ok()).toBe(true);
    await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('aria-busy', 'false');
    await expect(fitness.getByTestId('workflow-node-move-up')).toBeVisible();
    let saved = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
    expect(saved.workflow.graph.edges.some((edge: { from: string; to: string }) => edge.from === 'stays' && edge.to === 'fitness')).toBe(true);

    await fitness.locator('.editor-header .close-button').click();
    const movedByDrag = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
    await fitness.getByTestId('workflow-node-summary').dragTo(stays.getByTestId('workflow-node-summary'));
    expect((await movedByDrag).ok()).toBe(true);
    await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('aria-busy', 'false');
    saved = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
    expect(saved.workflow.graph.edges.some((edge: { from: string; to: string }) => edge.from === 'fitness' && edge.to === 'stays')).toBe(true);

    await stays.getByTestId('workflow-node-summary').click();
    await expect(stays.getByTestId('workflow-schema-field-date-range')).toBeVisible();
    await expect(stays.locator('input[id$="check_in_date"], input[id$="check_out_date"]')).toHaveCount(0);
    await stays.getByTestId('workflow-date-range-specific').click();
    await expect(stays.getByTestId('workflow-date-range-control')).toBeVisible();
  } finally {
    await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
  }
});
