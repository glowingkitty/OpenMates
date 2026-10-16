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
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');
const { copyRemoteHostSession, waitForFixtureEvent, stopFixtureProcess } = require('./helpers/project-remote-fixture');
const { email, password, otpKey } = getTestAccount();

test.describe('Workflow YAML files through CLI and REST', () => {
  test.setTimeout(180_000);

  // contract-test: direct surface=gui.web assertions=workflows.portability.remote-project-save,workflows.portability.private-content-boundary
  test('writes selected-folder YAML through the source bridge and updates it after browser Save', async ({ page }: { page: Page }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows', 'platform:projects']);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('workflow-source-file');
    const hostState = path.join(cliHome, 'remote-host');
    let bridge: any = null;
    let workflowId: string | null = null;
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'CLI_WORKFLOW_SOURCE_FILE');
      copyRemoteHostSession(path.join(cliHome, '.openmates'), hostState);
      bridge = spawn('node', ['--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs',
        'scripts/project_remote_access_live.mjs', 'serve-workflow', apiUrl], {
        cwd: path.resolve(__dirname, '../../../..'), stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, OPENMATES_STATE_DIR: hostState, OPENMATES_REMOTE_HOST_SESSION: path.join(hostState, 'session.json') },
      });
      const fixture = await waitForFixtureEvent(bridge, 'fixture_ready');
      expect(fixture.chat_id).toBeTruthy();
      const created = await page.request.post(`${apiUrl}/v1/workflows`, { data: { title: 'Portable remote', enabled: false,
        graph: { version: 2, trigger_node_id: null, nodes: [{ id: 'message', type: 'send_chat_message', config: { title: 'Remote note', message: 'Original remote message' } }], edges: [] } } });
      expect(created.ok(), await created.text()).toBeTruthy();
      workflowId = (await created.json()).workflow.id;
      const saved = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', workflowId!, 'add-to-project', fixture.project_id,
        '--remote-copy', '--source', fixture.source_id, '--remote-folder', 'src', '--source-chat', fixture.chat_id], 'write portable remote file');
      expect(saved.remote_file).toMatchObject({ status: 'saved', path: 'src/portable_remote.workflow.yml' });
      const readFile = async () => {
        const pending = waitForFixtureEvent(bridge, 'remote_file_state');
        bridge.kill('SIGUSR2');
        const result = await pending;
        expect(result.path).toBe('src/portable_remote.workflow.yml');
        return Buffer.from(result.content_base64, 'base64').toString('utf8');
      };
      const original = await readFile();
      expect(parse(original).format).toBe('openmates-workflow');
      expect(original).not.toContain(workflowId!);
      const bindingEvent = waitForFixtureEvent(bridge, 'workflow_remote_diagnostic', 10_000);
      bridge.kill('SIGQUIT');
      expect(await bindingEvent).toMatchObject({
        remote_file_status: 'saved', remote_file_error: null,
        source_online: true, project_binding_match: true,
      });
      await page.goto(`/#chat-id=${encodeURIComponent(fixture.chat_id)}&workflow-id=${encodeURIComponent(workflowId!)}&workflow-tab=details`, { waitUntil: 'domcontentloaded' });
      const node = page.locator('[data-testid="workflow-node-card"][data-node-id="message"]');
      await node.getByTestId('workflow-node-summary').click();
      await node.getByTestId('workflow-message-template').fill('Updated remote message');
      await node.getByTestId('workflow-node-save').click();
      try {
        await expect.poll(async () => parse(await readFile()).workflow.graph.nodes[0].config.message).toBe('Updated remote message');
      } catch (error) {
        try {
          const pending = waitForFixtureEvent(bridge, 'workflow_remote_diagnostic', 10_000);
          bridge.kill('SIGQUIT');
          const diagnostic = await pending;
          console.log('[CLI_WORKFLOW_REMOTE_DIAGNOSTIC] ' + JSON.stringify({
            remote_file_status: diagnostic.remote_file_status,
            remote_file_error: diagnostic.remote_file_error,
            source_online: diagnostic.source_online,
            project_binding_match: diagnostic.project_binding_match,
          }));
        } catch {
          console.log('[CLI_WORKFLOW_REMOTE_DIAGNOSTIC] unavailable');
        }
        throw error;
      }
      const external = waitForFixtureEvent(bridge, 'workflow_external_edit');
      bridge.kill('SIGWINCH');
      await external;
      await node.getByTestId('workflow-node-summary').click();
      await node.getByTestId('workflow-message-template').fill('Conflicting browser edit');
      await node.getByTestId('workflow-node-save').click();
      await expect(page.getByText(/remote YAML has changed/i).first()).toBeVisible();
      const retained = await readFile();
      expect(retained).toContain('External edit requires explicit reconciliation');
      expect(parse(retained).workflow.graph.nodes[0].config.message).toBe('Updated remote message');
      expect((await (await page.request.get(`${apiUrl}/v1/workflows/${workflowId}/runs`)).json()).runs).toEqual([]);
    } finally {
      if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${workflowId}`);
      if (bridge) await stopFixtureProcess(bridge);
      removeWorkflowCliHome(cliHome);
    }
  });

  // contract-test: direct surface=cli assertions=workflows.portability.remote-project-save
  test('keeps a pending remote YAML save recoverable without duplicate Workflow links', async ({ page }: { page: Page }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows', 'platform:projects']);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('workflow-pending-file');
    let projectId: string | null = null;
    let workflowId: string | null = null;
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'CLI_WORKFLOW_PENDING_FILE');
      const created = await runWorkflowCliJson(apiUrl, cliHome, ['projects', 'create', `Portable ${Date.now()}`, '--write-policy', 'apply_and_show'], 'create Project');
      projectId = created.projectId ?? created.project_id ?? created.project?.project_id;
      expect(projectId).toBeTruthy();
      const now = Math.floor(Date.now() / 1000);
      const sourceId = randomUUID();
      const projectResponse = await page.request.get(`${apiUrl}/v1/projects/${projectId}`);
      expect(projectResponse.ok()).toBeTruthy();
      const projectCiphertext = (await projectResponse.json()).project;
      const source = await page.request.post(`${apiUrl}/v1/projects/${projectId}/sources`, { data: {
        source_id: sourceId, source_type: 'remote_folder', encrypted_display_name: projectCiphertext.encrypted_name, encrypted_metadata: projectCiphertext.encrypted_description,
        capabilities: ['read', 'write_request'], status: 'offline', created_at: now, updated_at: now,
      } });
      expect(source.ok(), await source.text()).toBeTruthy();
      const response = await page.request.post(`${apiUrl}/v1/workflows`, { data: { title: 'Pending remote file', enabled: false,
        graph: { version: 2, trigger_node_id: null, nodes: [{ id: 'end', type: 'end', config: {} }], edges: [] } } });
      expect(response.ok(), await response.text()).toBeTruthy();
      workflowId = (await response.json()).workflow.id;
      for (let attempt = 0; attempt < 2; attempt++) {
        const saved = await runWorkflowCliJson(apiUrl, cliHome, ['workflows', workflowId!, 'add-to-project', projectId!, '--remote-copy', '--source', sourceId, '--remote-folder', 'automation'], 'save pending remote file');
        expect(saved.remote_file.status).toBe('pending');
        expect(saved.remote_file.path).toBeNull();
      }
      const items = await page.request.get(`${apiUrl}/v1/projects/${projectId}/items`);
      expect(items.ok()).toBeTruthy();
      expect((await items.json()).items.filter((item: any) => item.item_type === 'workflow')).toHaveLength(1);
      const runs = await page.request.get(`${apiUrl}/v1/workflows/${workflowId}/runs`);
      expect((await runs.json()).runs).toEqual([]);
    } finally {
      if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${workflowId}`);
      if (projectId) await page.request.delete(`${apiUrl}/v1/projects/${projectId}`);
      removeWorkflowCliHome(cliHome);
    }
  });

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
