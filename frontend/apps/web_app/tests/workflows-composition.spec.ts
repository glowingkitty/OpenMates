/* eslint-disable @typescript-eslint/no-require-imports */
/** Deterministic workflow composition: no AI/provider calls or real-account state. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
  createWorkflowCliHome, deleteWorkflowQuietly, expectCliSuccess, loginWorkflowCliViaPair,
  removeWorkflowCliHome, runWorkflowCli, runWorkflowCliJson, uniqueWorkflowName,
  waitForChatTitle, waitForWorkflowRunStatus, workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');
const { email, password, otpKey } = getTestAccount();

test.describe('Composable chat-owned workflows', () => {
  test.setTimeout(360_000);

  // contract-test: direct surface=cli assertions=workflows.control.for-each,workflows.chat.embedded-lifecycle,workflows.chat.invocation,workflows.chat.result-return
  // contract-test: direct surface=rest_api assertions=workflows.control.for-each,workflows.chat.embedded-lifecycle,workflows.chat.invocation,workflows.chat.result-return
  test('iterates caller inputs, returns selected outputs, and saves an independent reusable copy', async ({ page }: { page: any }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    const apiUrl = workflowApiUrl();
    const homeDir = createWorkflowCliHome('composable-workflows');
    let seedId: string | undefined;
    let workflowId: string | undefined;
    let savedId: string | undefined;
    let chatId: string | undefined;
    try {
      await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'WORKFLOW_COMPOSITION');
      const capabilities = await runWorkflowCliJson(apiUrl, homeDir,
        ['workflows', 'capabilities'], 'discover composable workflow controls');
      expect(capabilities.find((capability: any) => capability.id === 'for_each').enabled).toBe(true);
      const optionCheck = capabilities.find((capability: any) => capability.id === 'check.ai.options');
      expect(optionCheck.metadata.selection_modes).toEqual(['single', 'multiple']);
      expect(optionCheck.metadata.outputs).toContain('selected_options');
      expect(optionCheck.metadata.outputs).not.toContain('matched');
      // A deterministic Send creates an owned, client-encrypted chat without inference.
      const chatTitle = uniqueWorkflowName('Workflow caller');
      const seed = await page.request.post(`${apiUrl}/v1/workflows`, { data: {
        title: uniqueWorkflowName('Caller setup'), enabled: false,
        graph: { version: 2, trigger_node_id: 'start', nodes: [
          { id: 'start', type: 'manual_trigger', config: {} },
          { id: 'send', type: 'send_chat_message', config: { title: chatTitle, message: 'Workflow test caller' } }
        ], edges: [{ from: 'start', to: 'send' }] }
      }});
      expect(seed.ok(), await seed.text()).toBeTruthy();
      seedId = (await seed.json()).workflow.id;
      const seedRun = await runWorkflowCliJson(apiUrl, homeDir,
        ['workflows', 'run', seedId, '--idempotency-key', 'seed'], 'create deterministic caller chat');
      await waitForWorkflowRunStatus(apiUrl, homeDir, seedId, seedRun.id, ['completed'], 'caller setup');
      chatId = (await waitForChatTitle(apiUrl, homeDir, chatTitle)).id;
      expect(chatId).toBeTruthy();

      const graph = { version: 2, trigger_node_id: 'start', nodes: [
        { id: 'start', type: 'manual_trigger', config: { required_start_input_schema: {
          type: 'object', required: ['results'], properties: { results: {
            type: 'array', items: { type: 'object', properties: { keep: { type: 'boolean' } }, required: ['keep'] }
          }}
        }}},
        { id: 'loop', type: 'for_each', config: { items: 'trigger.results', max_items: 3 } },
        { id: 'check', type: 'check', config: { mode: 'exact', predicate: {
          left: '$items.loop.item.keep', op: 'eq', right: true
        }}}
      ], edges: [{ from: 'start', to: 'loop' }, { from: 'loop', to: 'check', branch: 'body' }] };
      const args = ['workflows', 'run-once', '--title', uniqueWorkflowName('Chat-owned list'),
        '--graph', JSON.stringify(graph), '--source-chat', chatId, '--idempotency-key', 'once',
        '--input', JSON.stringify({ results: [{ keep: true }, { keep: false }, { keep: true }] }),
        '--return-outputs', JSON.stringify({ processed: { ref: '$nodes.loop.output.completed_count', type: 'integer' } })];
      const accepted = await runWorkflowCliJson(apiUrl, homeDir, args, 'run chat-owned typed list');
      workflowId = accepted.workflow.id;
      expect(accepted.workflow.lifecycle).toBe('chat_embed');
      expect(accepted.workflow.auto_delete_at).toBeNull();
      expect(accepted.workflow.enabled).toBe(false);
      const immediateRetry = await runWorkflowCliJson(apiUrl, homeDir, args, 'retry immediately after acceptance');
      expect(immediateRetry.workflow.id).toBe(workflowId);
      expect(immediateRetry.run.id).toBe(accepted.run.id);
      const detail = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, accepted.run.id, ['completed'], 'typed list completion');
      const iterations = detail.node_runs.filter((node: any) => node.graph_node_id === 'check');
      expect(iterations.map((node: any) => node.iteration_index)).toEqual([0, 1, 2]);
      expect(iterations.every((node: any) => node.status === 'completed')).toBe(true);
      expect(detail.output_summary.nodes.loop.output.completed_count).toBe(3);
      const repeated = await runWorkflowCliJson(apiUrl, homeDir, args, 'retry accepted chat-owned run');
      expect(repeated.workflow.id).toBe(workflowId);
      expect(repeated.run.id).toBe(accepted.run.id);
      const library = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'inspect reusable library');
      const rows = Array.isArray(library) ? library : library.workflows;
      expect(rows.some((workflow: any) => workflow.id === workflowId)).toBe(false);
      let definitionEmbedId: string | undefined;
      await expect(async () => {
        const chat = await runWorkflowCliJson(apiUrl, homeDir, ['chats', 'show', chatId, '--all'], 'inspect caller return');
        const text = JSON.stringify(chat.messages);
        expect(text).toContain('processed');
        expect(text).toContain(accepted.run.id);
        definitionEmbedId = text.match(/embed:([a-f0-9-]{36})/i)?.[1];
        expect(definitionEmbedId, 'the chat contains a visible workflow definition embed').toBeTruthy();
      }).toPass({ timeout: 60_000 });
      const definition = await runWorkflowCliJson(apiUrl, homeDir,
        ['embeds', 'show', definitionEmbedId], 'decrypt chat-owned workflow definition');
      expect(definition.content.workflow_id).toBe(workflowId);
      expect(definition.content.lifecycle).toBe('chat_embed');
      expect(definition.content.graph.nodes.find((node: any) => node.id === 'loop').type).toBe('for_each');
      expect(definition.content.returned_outputs).toBeUndefined();

      const saveArgs = ['workflows', 'save-as-reusable', workflowId, '--idempotency-key', 'save-copy'];
      const saved = await runWorkflowCliJson(apiUrl, homeDir, saveArgs, 'save reusable copy');
      savedId = saved.id;
      expect(savedId).not.toBe(workflowId);
      expect(saved.lifecycle).toBe('persisted');
      expect(saved.enabled).toBe(false);
      expect((await runWorkflowCliJson(apiUrl, homeDir, saveArgs, 'retry copy')).id).toBe(savedId);
      const unauthorized = await page.request.post(`${apiUrl}/v1/workflows/${savedId}/run`, {
        headers: { 'Idempotency-Key': 'invalid-caller' }, data: { source_chat_id: '00000000-0000-0000-0000-000000000000' }
      });
      expect(unauthorized.status()).toBe(403);
      expectCliSuccess(await runWorkflowCli(apiUrl, homeDir,
        ['chats', 'delete', chatId, '--yes']), 'delete disposable caller');
      chatId = undefined;
      await expect(async () => {
        const deleted = await page.request.get(`${apiUrl}/v1/workflows/${workflowId}`);
        expect(deleted.status()).toBe(404);
      }).toPass({ timeout: 60_000 });
      expect((await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', savedId], 'inspect independent copy')).id).toBe(savedId);
    } finally {
      if (chatId) await runWorkflowCli(apiUrl, homeDir, ['chats', 'delete', chatId, '--yes']).catch(() => undefined);
      await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
      await deleteWorkflowQuietly(apiUrl, homeDir, savedId);
      await deleteWorkflowQuietly(apiUrl, homeDir, seedId);
      removeWorkflowCliHome(homeDir);
    }
  });
});
