/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { Page, Playwright } from '@playwright/test';

// Deterministic file transfer exercises the real authenticated API and CLI. It
// creates disposable workflows but never executes a provider or sends a chat.
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const {
  createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCli, runWorkflowCliJson, deleteWorkflowQuietly, workflowApiUrl,
} = require('./helpers/workflow-cli-e2e-helpers');
const fs = require('node:fs');
const path = require('node:path');
const { parse, stringify } = require('yaml');
const { email, password, otpKey } = getTestAccount();

test.describe('Workflow YAML files through CLI and REST', () => {
  test.setTimeout(180_000);

  // contract-test: direct surface=cli assertions=workflows.portability.definition-roundtrip,workflows.portability.private-content-boundary,workflows.portability.disabled-validated-import,workflows.portability.cli-commands
  test('exports and imports independent saved definitions without running them', async ({ page, playwright }: { page: Page; playwright: Playwright }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('workflow-files');
    const workflowIds: string[] = [];
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'CLI_WORKFLOW_FILES');
      const graph = {
        version: 2, trigger_node_id: null,
        nodes: [
          { id: 'first-send', type: 'send_chat_message', config: { title: 'First message', message: 'Morning update' }, ui: { x: 1 } },
          { id: 'second-send', type: 'send_chat_message', config: { title: 'Second message', message: 'Forwarded: {{$nodes.first-send.message}}' }, input_mapping: { label: '$nodes.first-send.message' } },
        ],
        edges: [{ from: 'first-send', to: 'second-send' }],
        variables: { label: 'morning' }, limits: {}, ui_layout: { 'first-send': { x: 1, y: 2 } },
      };
      const created = await page.request.post(`${apiUrl}/v1/workflows`, {
        data: { title: 'Portable morning update', description: 'Saved CLI transfer', graph, enabled: false, run_content_retention: 'none' },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
      const source = (await created.json()).workflow;
      workflowIds.push(source.id);
      const file = path.join(cliHome, 'morning.workflow.yml');
      const exported = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'export', source.id, '--output', file], 'export workflow');
      expect(exported).toBeTruthy();
      const yaml = fs.readFileSync(file, 'utf8');
      expect(yaml).toContain('format: openmates-workflow');
      expect(yaml).not.toContain(source.id);
      const document = parse(yaml);
      expect(document.workflow.run_content_retention).toBe('none');
      expect(document.workflow.graph.nodes[1].input_mapping.label).toBe('$nodes.step_1.message');

      const importedResult = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'import', '--file', file], 'import workflow');
      const imported = importedResult.workflow ?? importedResult;
      workflowIds.push(imported.id);
      expect(imported.id).not.toBe(source.id);
      expect(imported.enabled).toBe(false);
      const detail = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'show', imported.id], 'inspect imported workflow');
      const copied = detail.workflow ?? detail;
      expect(copied.title).toBe(source.title);
      expect(copied.description).toBe(source.description);
      expect(copied.run_content_retention).toBe('none');
      const first = copied.graph.nodes[0].id;
      expect(copied.graph.nodes[1].config.message).toBe(`Forwarded: {{$nodes.${first}.message}}`);
      expect(copied.graph.nodes[1].input_mapping.label).toBe(`$nodes.${first}.message`);
      expect(copied.graph.ui_layout[first]).toEqual({ x: 1, y: 2 });
      const runs = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'runs', imported.id], 'import creates no runs');
      expect(Array.isArray(runs) ? runs : runs.runs).toHaveLength(0);

      const blank = structuredClone(document);
      blank.workflow.title = 'Blank portable draft';
      blank.workflow.graph = { version: 2, trigger_node_id: null, nodes: [], edges: [] };
      blank.binding_requirements = [];
      fs.writeFileSync(file, stringify(blank));
      const draftResult = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'import', '--file', file], 'import blank workflow');
      const draft = draftResult.workflow ?? draftResult;
      workflowIds.push(draft.id);
      expect(draft.enabled).toBe(false);
      expect(draft.graph.nodes).toHaveLength(0);

      const before = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'list'], 'list before malformed import');
      fs.writeFileSync(file, 'format: openmates-workflow\nformat_version: [broken\n');
      const rejected = await runWorkflowCli(apiUrl, cliHome, ['workflows', 'import', '--file', file, '--json']);
      expect(rejected.code).not.toBe(0);
      const after = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', 'list'], 'list after malformed import');
      expect(after.map((item: { id: string }) => item.id).sort()).toEqual(before.map((item: { id: string }) => item.id).sort());

      const invalidVersion = await page.request.post(`${apiUrl}/v1/workflows/file-import`, { data: { ...blank, format_version: 99 } });
      expect(invalidVersion.status()).toBe(422);
      const anonymous = await playwright.request.newContext();
      try {
        const denied = await anonymous.post(`${apiUrl}/v1/workflows/file-import`, { data: blank });
        expect([401, 403]).toContain(denied.status());
      } finally { await anonymous.dispose(); }
    } finally {
      for (const id of workflowIds.reverse()) await deleteWorkflowQuietly(apiUrl, cliHome, id);
      removeWorkflowCliHome(cliHome);
    }
  });
});
