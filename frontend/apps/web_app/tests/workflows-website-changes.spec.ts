/* eslint-disable @typescript-eslint/no-require-imports -- Shared browser helpers use CommonJS. */
export {};
import type { Route } from '@playwright/test';
import type { WorkflowDetail, WorkflowGraph } from '@repo/ui/stores/workflowWorkspaceStore.ts';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' ? 'http://localhost:8000' : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Website change workflows', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.website-change.composition,workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.owned-library-and-templates
  test('creates the paused website starter with editable diff-only AI steps', async ({ page }) => {
    test.setTimeout(150000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});

    // Creation validates AI instructions through paid inference. CI exercises
    // the real template/card/store/projection UI with that API boundary mocked;
    // live provider validation remains a separate dev check.
    const id = '7658eea8-c5cd-4e69-9fd9-a52458ef8b31';
    const versionId = '573725f4-ddbc-4d1a-9531-cb343ac96c8b';
    let attempts = 0;
    let workflow: WorkflowDetail | null = null;
    let projection: Record<string, unknown> | null = null;
    let capabilitiesRequested = false;
    let releaseCapabilities!: () => void;
    const capabilitiesReady = new Promise<void>(resolve => { releaseCapabilities = resolve; });
    // Keep the real schema response pending until the first Check click, so
    // opening the freshly created template cannot erase its saved diff input.
    await page.route('**/v1/workflows/capabilities', async (route: Route) => {
      capabilitiesRequested = true;
      const response = await route.fetch();
      await capabilitiesReady;
      await route.fulfill({ response });
    });
    await page.route('**/v1/workflows', async (route: Route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ json: { workflows: workflow ? [workflow] : [] } });
        return;
      }
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      attempts += 1;
      if (attempts === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Template validation unavailable' } });
        return;
      }
      const body = route.request().postDataJSON();
      workflow = { ...body, id, version: 1, current_version_id: versionId, category: 'technology', icon: 'globe',
        status: 'active', created_at: Date.now() / 1000, updated_at: Date.now() / 1000, next_run_at: null };
      await route.fulfill({ json: { workflow } });
    });
    await page.route(`**/v1/workflows/${id}`, (route: Route) => route.fulfill({ json: { workflow } }));
    await page.route(`**/v1/workflows/${id}/runs`, (route: Route) => route.fulfill({ json: { runs: [] } }));
    await page.route(`**/v1/workflows/${id}/versions`, (route: Route) => route.fulfill({ json: { versions: [], current_version_id: versionId } }));
    await page.route(`**/v1/workflows/${id}/template-projection`, async (route: Route) => {
      if (route.request().method() === 'PUT') {
        projection = { ...route.request().postDataJSON(), updated_at: Date.now() / 1000 };
        await route.fulfill({ json: projection });
      } else {
        await route.fulfill(projection ? { json: projection } : { status: 404, json: { detail: 'No projection' } });
      }
    });

    await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workflows-show-templates').click();
    const starter = page.getByTestId('workflow-landing-card').filter({ hasText: 'Website changes' });
    await expect(starter).toContainText('events.ccc.de');
    await expect(starter).toHaveAttribute('data-icon', 'globe');
    await starter.click();
    await expect(page.getByTestId('workflows-error')).toContainText('Template validation unavailable');
    expect(workflow).toBeNull();
    await expect(starter).toBeVisible();
    await starter.click();
    await expect(page.getByTestId('workspace-detail-title')).toHaveText('Website changes');
    await expect(page.getByTestId('toggle-workflow')).toHaveAttribute('aria-checked', 'false');
    await expect.poll(() => projection).not.toBeNull();
    expect(attempts).toBe(2);
    const created = workflow as unknown as WorkflowDetail;
    expect(created.enabled).toBe(false);
    expect(created.description).toContain('first successful read');
    const graph = created.graph as WorkflowGraph;
    expect(graph.nodes).toHaveLength(5);
    expect(graph.nodes.find(node => node.id === 'trigger')?.config?.schedule).toMatchObject({ type: 'daily', time: '09:00' });
    expect(graph.nodes.find(node => node.id === 'read')?.config?.input).toEqual({ requests: [{ url: 'https://events.ccc.de/', only_main_content: true, max_age: 0 }] });
    expect(graph.nodes.find(node => node.id === 'check')?.config).toMatchObject({ mode: 'ai', selected_inputs: ['$nodes.read.output.changes'] });
    expect(graph.edges.filter(edge => edge.from === 'check')).toEqual([{ from: 'check', to: 'summary', branch: 'true' }]);
    const summaryInput = graph.nodes.find(node => node.id === 'summary')?.config?.input as { prompt: string };
    expect(summaryInput.prompt).toContain('{{steps.read.changes}}');
    expect(summaryInput.prompt).not.toContain('{{steps.read.text}}');
    expect(graph.nodes.find(node => node.id === 'message')?.config?.message).toContain('{{steps.summary.answer}}');
    expect(graph.nodes.find(node => node.id === 'message')?.config?.message).toContain('{{steps.read.source_url}}');
    const check = page.locator('[data-node-id="check"]');
    await expect.poll(() => capabilitiesRequested).toBe(true);
    await check.getByTestId('workflow-node-summary').click();
    releaseCapabilities();
    await expect(check.getByTestId('workflow-message-template')).toContainText('Chaos Communication Congress');
    await expect(check.getByTestId('workflow-message-template').locator('.generic-mention')).toHaveAttribute('title', /Changes since last successful read$/);
    await expect(check.getByTestId('workflow-website-change-guidance')).toContainText('without sending a message');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('workspace-detail-title')).toHaveText('Website changes');
    await expect(page.getByTestId('toggle-workflow')).toHaveAttribute('aria-checked', 'false');
    await check.getByTestId('workflow-node-summary').click();
    await expect(check.getByTestId('workflow-message-template').locator('.generic-mention')).toHaveAttribute('title', /Changes since last successful read$/);
  });

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
