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
test('reorders persisted nodes and renders real date and location controls from a skill without a configured-provider dependency', async ({ page }: { page: Page }) => {
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
      { id: 'berlin', type: 'app_skill_action', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', start_date: tomorrow, end_date: later } } },
      { id: 'paris', type: 'app_skill_action', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Paris', start_date: tomorrow, end_date: later } } },
    ],
    edges: [{ from: 'trigger', to: 'berlin' }, { from: 'berlin', to: 'paris' }],
  };
  const created = await page.request.post(`${apiUrl()}/v1/workflows`, {
    data: { title: `Workflow reorder controls ${Date.now()}`, graph, enabled: false },
  });
  expect(created.ok()).toBe(true);
  const { workflow } = await created.json();
  try {
    await page.goto(getE2EDebugUrl('/#workflows'), { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByTestId('workflow-landing-card').filter({ hasText: workflow.title }).first().click();
    const berlin = page.locator('[data-node-id="berlin"]');
    const paris = page.locator('[data-node-id="paris"]');

    await berlin.getByTestId('workflow-node-summary').click();
    await expect(berlin.getByTestId('workflow-node-move-up')).toHaveCount(0);
    await expect(berlin.getByTestId('workflow-node-move-down')).toBeVisible();
    await expect(berlin.getByTestId('workflow-schema-field-location').getByTestId('workflow-node-location-picker')).toBeVisible();
    await expect(berlin.getByTestId('workflow-schema-field-date-range')).toBeVisible();
    await expect(berlin.locator('input[id$="start_date"], input[id$="end_date"]')).toHaveCount(0);
    await berlin.getByTestId('workflow-date-range-specific').click();
    await expect(berlin.getByTestId('workflow-date-range-control')).toBeVisible();

    const movedByButton = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
    await berlin.getByTestId('workflow-node-move-down').click();
    expect((await movedByButton).ok()).toBe(true);
    await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('aria-busy', 'false');
    await expect(berlin.getByTestId('workflow-node-move-up')).toBeVisible();
    let saved = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
    expect(saved.workflow.graph.edges.some((edge: { from: string; to: string }) => edge.from === 'paris' && edge.to === 'berlin')).toBe(true);

    const ownerProjection = await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}/template-projection`);
    expect(ownerProjection.ok()).toBe(true);
    const stableTemplateId = (await ownerProjection.json()).template_id;
    await page.evaluate(() => localStorage.removeItem('openmates.workflow-template-projections.v1'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(berlin.getByTestId('workflow-node-summary')).toBeVisible();
    await berlin.getByTestId('workflow-node-summary').scrollIntoViewIfNeeded();

    const movedByDrag = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
    const source = await berlin.getByTestId('workflow-node-summary').boundingBox();
    expect(source).not.toBeNull();
    await page.mouse.move(source!.x + source!.width / 2, source!.y + source!.height / 2);
    await page.mouse.down();
    await page.mouse.move(source!.x + source!.width / 2 + 20, source!.y + source!.height / 2 + 20, { steps: 5 });
    const drop = page.locator('[data-testid="workflow-node-drop-zone"][data-after-node-id="trigger"]');
    await expect(drop).toBeVisible();
    await expect(drop).toHaveText('Drop here to move');
    // The zone opens above the dragged node and can sit under the fixed header; scroll it into view while dragging.
    await drop.evaluate((element: HTMLElement) => element.scrollIntoView({ block: 'center' }));
    const target = await drop.boundingBox();
    expect(target).not.toBeNull();
    await page.mouse.move(target!.x + target!.width / 2, target!.y + target!.height / 2, { steps: 8 });
    await expect(drop).toHaveClass(/drop-slot/);
    await page.mouse.up();
    expect((await movedByDrag).ok()).toBe(true);
    await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('aria-busy', 'false');
    await expect(page.locator('[data-node-id="berlin"] + .connector + [data-node-id="paris"]')).toBeVisible();
    saved = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
    expect(saved.workflow.graph.edges.some((edge: { from: string; to: string }) => edge.from === 'berlin' && edge.to === 'paris')).toBe(true);
    const recoveredProjection = await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}/template-projection`);
    expect((await recoveredProjection.json()).template_id).toBe(stableTemplateId);
    await expect(page.getByText('Workflow saved, but its shareable template was not updated:', { exact: false })).toHaveCount(0);

    let releaseTest!: () => void;
    let testRequestSeen!: () => void;
    const testGate = new Promise<void>(resolve => { releaseTest = resolve; });
    const requestSeen = new Promise<void>(resolve => { testRequestSeen = resolve; });
    await page.route(`**/v1/workflows/${workflow.id}/steps/berlin/test`, async route => {
      testRequestSeen();
      await testGate;
      await route.fulfill({ json: { run: {
        id: 'fixture-berlin-test', workflow_id: workflow.id, version_id: workflow.current_version_id,
        status: 'completed', node_runs: [{ node_id: 'berlin', status: 'completed', output_summary: {
          results: [{ id: 'request-1', result_count: 2, results: [
            { date: tomorrow, condition: 'Light rain', temperature_max_c: 14 },
            { date: later, condition: 'Clear sky', temperature_max_c: 19 },
          ] }],
        } }],
      } } });
    });
    await berlin.getByTestId('workflow-node-summary').click();
    await berlin.getByTestId('workflow-test-action').click();
    await requestSeen;
    await expect(berlin.getByTestId('workflow-show-output-fields')).toHaveAttribute('aria-expanded', 'true');
    await expect(berlin.getByTestId('workflow-test-output-loading')).toBeVisible();
    releaseTest();
    const carousel = berlin.getByTestId('workflow-result-carousel');
    await carousel.locator('summary').first().click();
    await expect(carousel).toContainText('Light rain');
    await carousel.getByTestId('workflow-result-next').click();
    await carousel.locator('summary').first().click();
    await expect(carousel).toContainText('Clear sky');
    await berlin.locator('.editor-header .close-button').click();

    await paris.getByTestId('workflow-node-summary').click();
    await expect(paris.getByTestId('workflow-schema-field-date-range')).toBeVisible();
    await expect(paris.locator('input[id$="check_in_date"], input[id$="check_out_date"]')).toHaveCount(0);
    await paris.getByTestId('workflow-date-range-specific').click();
    await expect(paris.getByTestId('workflow-date-range-control')).toBeVisible();
  } finally {
    await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
  }
});
