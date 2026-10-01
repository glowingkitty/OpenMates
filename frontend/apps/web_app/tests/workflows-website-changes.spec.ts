/* eslint-disable @typescript-eslint/no-require-imports -- Shared browser helpers use CommonJS. */
export {};
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' ? 'http://localhost:8000' : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Website change workflows', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.website-change.composition,workflows.website-change.diff-inputs
  // contract-test: supporting surface=rest_api assertions=workflows.website-change.lifecycle
  test('saves typed change references and tests an exact condition without reading or sending', async ({ page }) => {
    test.setTimeout(150000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    const graph = {
      version: 2, trigger_node_id: 'trigger',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', config: {} },
        { id: 'read', type: 'app_skill_action', config: { app_id: 'web', skill_id: 'read', input: { requests: [{ url: 'https://events.ccc.de/' }] } } },
        { id: 'check', type: 'check', config: { mode: 'exact', predicate: { left: '$nodes.read.output.has_changed', op: 'eq', right: true } } },
        { id: 'send', type: 'send_chat_message', config: { title: 'Congress updates', message: '{{steps.read.changes}}\n{{steps.read.source_url}}' } },
      ],
      edges: [{ from: 'trigger', to: 'read' }, { from: 'read', to: 'check' }, { from: 'check', to: 'send', branch: 'yes' }],
    };
    const created = await page.request.post(`${apiUrl()}/v1/workflows`, { data: { title: `Website change ${Date.now()}`, graph, enabled: false } });
    expect(created.ok(), await created.text()).toBe(true);
    const { workflow } = await created.json();
    try {
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workflow-landing-card').filter({ hasText: workflow.title }).first().click();
      const check = page.locator('[data-node-id="check"]');
      await check.getByTestId('workflow-node-summary').click();
      await expect(check.getByTestId('workflow-check-variable')).toContainText('Has changed since last successful read');
      await expect(check.getByTestId('workflow-website-change-guidance')).toContainText('Failed or blocked reads');
      await check.getByTestId('workflow-check-variable').click();
      await expect(page.getByRole('option', { name: 'Changes since last successful read', exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
      const saved = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
      await check.getByTestId('workflow-node-save').click();
      expect((await saved).ok()).toBe(true);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await check.getByTestId('workflow-node-summary').click();
      await expect(check.getByTestId('workflow-check-variable')).toContainText('Has changed since last successful read');
      const before = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
      for (const hasChanged of [true, false]) {
        const tested = await page.request.post(`${apiUrl()}/v1/workflows/${workflow.id}/steps/check/test`, {
          data: { upstream_outputs: { read: { has_changed: hasChanged, changes: hasChanged ? '+Congress announcement' : '', source_url: 'https://events.ccc.de/' } } },
        });
        expect(tested.ok(), await tested.text()).toBe(true);
        const { run } = await tested.json();
        expect(run.status).toBe('completed');
        expect(run.node_runs).toHaveLength(1);
        expect(run.node_runs[0].node_id).toBe('check');
        expect(run.node_runs[0].output_summary.matched).toBe(hasChanged);
        expect(run.node_runs[0].credit_cost).toBe(0);
        expect(run.cost_summary).toEqual({});
      }
      const after = await (await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)).json();
      expect(after.workflow.current_version_id).toBe(before.workflow.current_version_id);
      expect(after.workflow.graph).toEqual(before.workflow.graph);
      expect(after.workflow.graph.nodes.find(node => node.id === 'check').config.predicate.left).toBe('$nodes.read.output.has_changed');
    } finally {
      expect((await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`)).ok()).toBe(true);
    }
  });
});
