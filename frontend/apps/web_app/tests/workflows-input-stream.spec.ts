/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : `${url.protocol}//api.${url.hostname.replace(/^app\./, '')}`;
}

const graph = {
  version: 2, trigger_node_id: 'manual',
  nodes: [
    { id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} },
    { id: 'message', type: 'send_chat_message', title: 'Send report', config: { message: 'Ready' } }
  ], edges: [{ from: 'manual', to: 'message' }]
};

test.describe('streamed workflow authoring', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,workflows-ui.authoring.edit-control-and-undo
  test('renders fragmented provisional graphs through repeated corrections, clears rejection, and opens committed results', async ({ page }: { page: Page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      const streamWindow = window as typeof window & { __workflowStreamCases?: Array<{ events: unknown[]; holdOpen?: boolean; holdResponse?: boolean }>; __workflowStreamCalls?: number; __workflowStreamBodies?: Array<Record<string, unknown>>; __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array>; __workflowReleaseResponse?: () => void };
      streamWindow.__workflowStreamCases = [];
      streamWindow.__workflowStreamCalls = 0;
      streamWindow.__workflowStreamBodies = [];
      window.fetch = async (input, init) => {
        if (!String(input).includes('/v1/workflows/input/stream')) return originalFetch(input, init);
        const scenario = streamWindow.__workflowStreamCases?.shift();
        if (!scenario) throw new Error('Missing workflow stream scenario');
        streamWindow.__workflowStreamCalls = (streamWindow.__workflowStreamCalls ?? 0) + 1;
        streamWindow.__workflowStreamBodies?.push(JSON.parse(String(init?.body ?? '{}')));
        streamWindow.__workflowOpenStream = undefined;
        if (scenario.holdResponse) await new Promise<void>(resolve => { streamWindow.__workflowReleaseResponse = resolve; });
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            if (scenario.holdOpen) streamWindow.__workflowOpenStream = controller;
            init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true });
            scenario.events.forEach((event, index) => {
              const frame = `data: ${JSON.stringify(event)}\n\n`;
              const split = Math.floor(frame.length / 2);
              setTimeout(() => controller.enqueue(encoder.encode(frame.slice(0, split))), index * 700);
              setTimeout(() => {
                controller.enqueue(encoder.encode(frame.slice(split)));
                if (index === scenario.events.length - 1 && !scenario.holdOpen) controller.close();
              }, index * 700 + 35);
            });
          }
        });
        return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
      };
    });
    const log = (message: string) => console.log(`[WORKFLOW_STREAM_E2E] ${message}`);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, async () => {});
    const created: string[] = [];
    const retryGraph = {
      ...graph,
      nodes: [...graph.nodes, { id: 'followup', type: 'send_chat_message', title: 'Send follow-up', config: { message: 'Follow up' } }],
      edges: [...graph.edges, { from: 'message', to: 'followup' }]
    };
    const seed = async (title: string, workflowGraph = graph) => {
      const response = await page.request.post(`${apiUrl()}/v1/workflows`, { data: { title, graph: workflowGraph, enabled: false } });
      expect(response.ok(), await response.text()).toBe(true);
      const workflow = (await response.json()).workflow;
      created.push(workflow.id);
      return workflow;
    };
    try {
      const one = await seed(`Stream one ${Date.now()}`);
      const two = await seed(`Stream two ${Date.now()}`);
      const retried = await seed(`Stream retried ${Date.now()}`, retryGraph);
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflow-input-textarea')).toBeVisible();
      let provisionalFetches = 0;
      page.on('request', request => { if (/\/v1\/workflows\/provisional-/.test(request.url())) provisionalFetches += 1; });
      const configure = (events: unknown[], holdOpen = false, holdResponse = false) => page.evaluate(({ events, holdOpen, holdResponse }) => {
        (window as typeof window & { __workflowStreamCases: Array<{ events: unknown[]; holdOpen?: boolean; holdResponse?: boolean }> }).__workflowStreamCases.push({ events, holdOpen, holdResponse });
      }, { events, holdOpen, holdResponse });
      const preview = (workflow: { id: string; title: string }, index: number, accepted = 2, workflowGraph = graph) => ({
        type: 'preview', workflow_index: index, operation: 'create',
        graph: { ...workflowGraph, nodes: workflowGraph.nodes.slice(0, accepted), edges: workflowGraph.edges.filter(edge => workflowGraph.nodes.slice(0, accepted).some(node => node.id === edge.to)) },
        metadata: { title: workflow.title }, accepted_node_count: accepted,
        node: workflowGraph.nodes[accepted - 1], provisional: true, validated: true
      });
      await configure([
        { type: 'started', session_id: 'rejected-stream', status: 'running' }
      ], true);
      await page.getByTestId('workflow-input-textarea').fill('Rejected workflow request');
      await page.getByTestId('workflow-input-submit').click();
      await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('workflow-ai-pending') || '{}'))).toEqual({ sessionId: 'rejected-stream' });
      expect(await page.evaluate(() => (window as typeof window & { __workflowStreamBodies: Array<Record<string, unknown>> }).__workflowStreamBodies[0]?.idempotency_key)).toMatch(/^[0-9a-f-]{36}$/);
      await page.evaluate(() => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode('data: {"type":"session","session":{"session_id":"rejected-stream","status":"failed","error":"The request needs a clearer trigger."}}\n\n'));
        stream.close();
      });
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
      await expect(page.getByTestId('workflows-error')).toContainText('clearer trigger');
      await expect(page.getByText('Confirm', { exact: true })).toHaveCount(0);

      let statusReads = 0;
      await page.route('**/v1/workflows/input/disconnect-stream', async route => {
        statusReads += 1;
        const session = statusReads === 1
          ? { session_id: 'disconnect-stream', status: 'running' }
          : { session_id: 'disconnect-stream', status: 'executed', workflows: [one], mutations: [{ type: 'create_workflow', target_id: one.id }] };
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session }) });
      });
      const callsBeforeDisconnect = await page.evaluate(() => (window as typeof window & { __workflowStreamCalls: number }).__workflowStreamCalls);
      await configure([
        { type: 'started', session_id: 'disconnect-stream', status: 'running' },
        preview(one, 0)
      ]);
      await page.getByTestId('workflow-input-textarea').fill('Recover a disconnected workflow');
      await page.getByTestId('workflow-input-submit').click();
      await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
      await expect.poll(() => statusReads).toBeGreaterThanOrEqual(2);
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
      await expect(page.getByTestId('workflow-ai-edit-textarea')).toBeEnabled();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(one.title);
      expect(await page.evaluate(() => (window as typeof window & { __workflowStreamCalls: number }).__workflowStreamCalls)).toBe(callsBeforeDisconnect + 1);
      await page.getByTestId('workflow-detail-back').click();

      await configure([], true, true);
      await page.getByTestId('workflow-input-textarea').fill('Single workflow request');
      await page.getByTestId('workflow-input-submit').click();
      await expect(page.getByTestId('workflow-management')).toBeVisible();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText('Processing…');
      await expect(page.getByTestId('workflow-ai-processing')).toContainText('Processing');
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(0);
      await expect(page.getByTestId('workflow-ai-editor-composer')).toBeVisible();
      await expect(page.getByTestId('workflow-ai-stop')).toBeVisible();
      await expect.poll(() => page.evaluate(() => typeof (window as typeof window & { __workflowReleaseResponse?: () => void }).__workflowReleaseResponse)).toBe('function');
      await page.evaluate(() => {
        const release = (window as typeof window & { __workflowReleaseResponse?: () => void }).__workflowReleaseResponse;
        if (!release) throw new Error('Workflow response was not held');
        release();
      });
      await expect(page.getByTestId('workflow-ai-pending')).toBeVisible();
      await expect.poll(() => page.evaluate(() => typeof (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream)).toBe('object');
      await page.evaluate(() => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode('data: {"type":"started","session_id":"single-stream","status":"running"}\n\ndata: {"type":"progress","phase":"planning","operation":"create","workflow_count":1}\n\n'));
      });
      await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('workflow-ai-pending') || '{}'))).toEqual({ sessionId: 'single-stream' });
      const singleHeader = { ...preview(retried, 0, 1, retryGraph), accepted_node_count: 0, metadata: { title: retried.title, description: 'A draft with validated steps' } };
      await page.evaluate((event) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      }, singleHeader);
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(retried.title);
      await expect(page.getByTestId('workspace-detail-description')).toHaveText('A draft with validated steps');
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(1);
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveCount(0);
      // Controlled SSE verifies the browser handoff; provider retries and server saving are covered separately.
      await page.evaluate(() => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode('data: {"type":"progress","phase":"retrying_node","workflow_index":0,"node_index":0,"attempt":2}\n\n'));
      });
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-save-status', 'retrying_node');
      await expect(page.getByTestId('workflow-ai-pending')).toBeVisible();
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(1);
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveCount(0);
      await page.evaluate(() => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode('data: {"type":"progress","phase":"validating","workflow_index":0,"node_index":0}\n\n'));
      });
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-save-status', 'validating');
      await page.evaluate((event) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      }, { ...preview(retried, 0, 2, retryGraph), accepted_node_count: 1, metadata: singleHeader.metadata });
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(2);
      await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-disabled', 'true');
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveText('1 step validated');
      await expect(page.getByTestId('workflow-ai-editor-composer')).toBeVisible();
      await expect(page.getByTestId('workflow-ai-edit-textarea')).toBeDisabled();
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card').first()).toBeVisible();
      await expect(page.getByTestId('delete-workflow')).toHaveCount(0);
      await expect(page.getByTestId('workflow-export')).toHaveCount(0);
      await expect(page.getByTestId('workflow-version-selector')).toHaveCount(0);
      await expect(page.getByTestId('workflow-ai-stop')).toBeVisible();
      await page.evaluate(() => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode('data: {"type":"progress","phase":"retrying_node","workflow_index":0,"node_index":1,"attempt":3}\n\n'));
      });
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-save-status', 'retrying_node');
      await expect(page.getByTestId('workflow-ai-pending')).toBeVisible();
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveText('1 step validated');
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(2);
      await expect(page.getByTestId('workflow-ai-stop')).toBeVisible();
      await page.evaluate((event) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      }, { ...preview(retried, 0, 3, retryGraph), accepted_node_count: 2, metadata: singleHeader.metadata });
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveText('2 steps validated');
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(3);
      expect(provisionalFetches).toBe(0);
      await page.evaluate((workflow) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: 'progress', phase: 'saving' })}\n\ndata: ${JSON.stringify({ type: 'session', session: { session_id: 'single-stream', status: 'executed', workflows: [workflow], mutations: [{ type: 'create_workflow', target_id: workflow.id }] } })}\n\n`));
        stream.close();
      }, retried);
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
      await expect(page.getByTestId('workflow-ai-edit-textarea')).toBeEnabled();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(retried.title);
      await expect(page.getByTestId('workflow-template-panel').getByTestId('workflow-node-card')).toHaveCount(3);
      await page.getByTestId('workflow-detail-back').click();
      await expect(page.getByTestId('workflow-landing-card').filter({ hasText: retried.title })).toHaveCount(1);

      await configure([
        { type: 'started', session_id: 'multi-stream', status: 'running' },
        { type: 'progress', phase: 'planning', operation: 'create', workflow_count: 2 }, preview(one, 0), preview(two, 1)
      ], true);
      await page.getByTestId('workflow-input-textarea').fill('Two workflow request');
      await page.getByTestId('workflow-input-submit').click();
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(2);
      await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
      await expect(page.getByTestId('workflow-management')).toHaveCount(0);
      await page.evaluate(({ one, two }) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: 'session', session: { session_id: 'multi-stream', status: 'executed', workflows: [one, two], mutations: [{ type: 'create_workflow', target_id: one.id }, { type: 'create_workflow', target_id: two.id }] } })}\n\n`));
        stream.close();
      }, { one, two });
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
      await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
      for (const workflow of [one, two]) {
        const card = page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: workflow.title });
        await expect(card).toBeVisible();
        await expect(card.locator('..').getByTestId('workflow-new-pill')).toHaveText('New');
      }

      let stopCalls = 0;
      let partialReads = 0;
      await page.route('**/v1/workflows/input/stop-stream/stop', async route => {
        stopCalls += 1;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { session_id: 'stop-stream', status: 'running', stop_requested: true } }) });
      });
      await page.route('**/v1/workflows/input/stop-stream', async route => {
        partialReads += 1;
        const session = partialReads === 1
          ? { session_id: 'stop-stream', status: 'running', stop_requested: true }
          : { session_id: 'stop-stream', status: 'draft', partial_reason: 'stopped', partial_warning: 'Saved completed steps. Add the remaining step manually or ask for a specific update.', workflows: [one], mutations: [{ type: 'create_workflow', target_id: one.id }] };
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session }) });
      });
      await configure([
        { type: 'started', session_id: 'stop-stream', status: 'running' },
        { type: 'progress', phase: 'planning', operation: 'create', workflow_count: 1 },
        { type: 'progress', phase: 'validating' }, preview(one, 0, 1),
        { type: 'progress', phase: 'retrying_node' }, preview(one, 0, 2)
      ], true);
      await page.getByTestId('workflow-input-textarea').fill('Create a workflow, then stop after the valid steps');
      await page.getByTestId('workflow-input-submit').click();
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveText('1 step validated');
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveText('2 steps validated');
      await page.getByTestId('workflow-ai-stop').click();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(one.title);
      await expect(page.getByTestId('workflow-ai-partial-warning')).toContainText('Saved completed steps');
      expect(stopCalls).toBe(1);
      expect(partialReads).toBeGreaterThanOrEqual(2);
    } finally {
      for (const id of created) await page.request.delete(`${apiUrl()}/v1/workflows/${id}`).catch(() => null);
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.edit-control-and-undo,workflows.authoring.atomic-update
  test('stopped streamed edit keeps the original workflow and guards Undo after a later version', async ({ page }: { page: Page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      const state = window as typeof window & {
        __editStreams?: Array<{ sessionId: string; preview: unknown }>;
        __editStreamBodies?: Array<Record<string, unknown>>;
      };
      state.__editStreams = [];
      state.__editStreamBodies = [];
      window.fetch = async (input, init) => {
        if (!String(input).includes('/v1/workflows/input/stream')) return originalFetch(input, init);
        const scenario = state.__editStreams?.shift();
        if (!scenario) throw new Error('Missing partial edit stream scenario');
        state.__editStreamBodies?.push(JSON.parse(String(init?.body ?? '{}')));
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true });
            for (const event of [
              { type: 'started', session_id: scenario.sessionId, status: 'running' },
              { type: 'progress', phase: 'validating', operation: 'update', workflow_count: 1 },
              scenario.preview
            ]) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
          }
        });
        return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
      };
    });
    const log = (message: string) => console.log(`[WORKFLOW_PARTIAL_EDIT_E2E] ${message}`);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, async () => {});
    const originalGraph = {
      version: 2, trigger_node_id: 'trigger',
      nodes: [
        { id: 'trigger', type: 'schedule_trigger', title: 'Every morning', config: { schedule: { type: 'daily', time: '07:00', timezone: 'Europe/Berlin' } } },
        { id: 'message', type: 'send_chat_message', title: 'Send report', config: { title: 'Daily report', message: 'Original report' } },
        { id: 'later', type: 'send_chat_message', title: 'Later follow-up', config: { title: 'Follow-up report', message: 'Keep this step' } }
      ],
      edges: [{ from: 'trigger', to: 'message' }, { from: 'message', to: 'later' }]
    };
    const seedResponse = await page.request.post(`${apiUrl()}/v1/workflows`, { data: {
      title: `Partial edit ${Date.now()}`, description: 'Original description', category: 'general_knowledge', icon: 'calendar', graph: originalGraph, enabled: true
    } });
    expect(seedResponse.ok(), await seedResponse.text()).toBe(true);
    const original = (await seedResponse.json()).workflow;
    const workflowUrl = `${apiUrl()}/v1/workflows/${original.id}`;
    const readWorkflow = async () => (await (await page.request.get(workflowUrl)).json()).workflow;
    const editedGraph = { ...original.graph, nodes: original.graph.nodes.map((node: typeof originalGraph.nodes[number]) =>
      node.id === 'message' ? { ...node, title: 'Send revised report', config: { ...node.config, message: 'Revised report' } } : node) };
    let current = original;
    let undoCalls = 0;
    try {
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workflow-landing-card').filter({ hasText: original.title }).click();
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'true');
      const stopCounts = new Map<string, number>();
      const statusCounts = new Map<string, number>();
      for (const sessionId of ['partial-edit-first', 'partial-edit-second']) {
        await page.route(`**/v1/workflows/input/${sessionId}/stop`, async route => {
          stopCounts.set(sessionId, (stopCounts.get(sessionId) ?? 0) + 1);
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { session_id: sessionId, status: 'running', stop_requested: true } }) });
        });
        await page.route(`**/v1/workflows/input/${sessionId}`, async route => {
          const reads = (statusCounts.get(sessionId) ?? 0) + 1;
          statusCounts.set(sessionId, reads);
          if (reads === 1) {
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { session_id: sessionId, status: 'running', stop_requested: true } }) });
            return;
          }
          if (reads === 2) {
            const response = await page.request.patch(workflowUrl, { data: {
              title: 'Partially revised workflow', description: 'Revised description', icon: 'workflow', graph: editedGraph, enabled: false
            } });
            expect(response.ok(), await response.text()).toBe(true);
            current = (await response.json()).workflow;
          }
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: {
            session_id: sessionId, status: 'draft', partial_reason: 'stopped', partial_warning: 'Saved completed steps; later steps remain.',
            workflows: [current], undo_available: true,
            mutations: [{ type: 'update_workflow', target_id: original.id, before: original, after: current }]
          } }) });
        });
        await page.route(`**/v1/workflows/input/${sessionId}/undo`, async route => {
          undoCalls += 1;
          if (sessionId === 'partial-edit-first') {
            const response = await page.request.patch(workflowUrl, { data: {
              title: original.title, description: original.description, icon: original.icon, graph: original.graph, enabled: original.enabled
            } });
            expect(response.ok(), await response.text()).toBe(true);
            current = (await response.json()).workflow;
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { session_id: sessionId, status: 'undone' } }) });
          } else {
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: {
              session_id: sessionId, status: 'draft', error_code: 'WORKFLOW_INPUT_UNDO_CONFLICT', error: 'A newer change prevents Undo.'
            } }) });
          }
        });
      }
      const stopEdit = async (sessionId: string) => {
        await page.evaluate(({ sessionId, id, title, graph }) => {
          (window as typeof window & { __editStreams: Array<{ sessionId: string; preview: unknown }> }).__editStreams.push({
            sessionId, preview: { type: 'preview', workflow_index: 0, operation: 'update', provisional: true, validated: true,
              graph, metadata: { workflow_id: id, title, description: 'Revised description', icon: 'workflow' }, accepted_node_count: 2 }
          });
        }, { sessionId, id: original.id, title: 'Partially revised workflow', graph: editedGraph });
        await page.getByTestId('workflow-ai-edit-textarea').fill('Revise only the report step');
        await page.getByTestId('workflow-ai-edit-submit').click();
        await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-ai-accepted-nodes')).toHaveText('2 steps validated');
        await page.getByTestId('workflow-ai-stop').click();
        await expect(page.getByTestId('workflow-ai-partial-warning')).toContainText('later steps remain');
        await expect(page.getByTestId('workspace-detail-title')).toHaveText('Partially revised workflow');
        await expect(page.getByTestId('workspace-detail-description')).toHaveText('Revised description');
        await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-icon', 'workflow');
        await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false');
        await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="message"]')).toHaveAttribute('data-ai-change', 'edited');
        await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="later"]')).toBeVisible();
        expect(stopCounts.get(sessionId)).toBe(1);
        expect(statusCounts.get(sessionId)).toBeGreaterThanOrEqual(2);
        const saved = await readWorkflow();
        expect(saved.id).toBe(original.id);
        expect(saved.graph.nodes.find((node: { id: string }) => node.id === 'message')?.config).toEqual(editedGraph.nodes.find((node: { id: string }) => node.id === 'message')?.config);
        expect(saved.graph.nodes.find((node: { id: string }) => node.id === 'later')).toEqual(original.graph.nodes.find((node: { id: string }) => node.id === 'later'));
        expect(saved.graph.edges).toEqual(original.graph.edges);
      };
      await stopEdit('partial-edit-first');
      await page.getByTestId('workflow-ai-undo').click();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(original.title);
      await expect(page.getByTestId('workspace-detail-description')).toHaveText(original.description);
      await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-icon', original.icon);
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'true');
      expect((await readWorkflow()).graph).toEqual(original.graph);

      await stopEdit('partial-edit-second');
      const manualResponse = await page.request.patch(workflowUrl, { data: { description: 'Later manual version' } });
      expect(manualResponse.ok(), await manualResponse.text()).toBe(true);
      const manualVersion = (await manualResponse.json()).workflow;
      await page.getByTestId('workflow-ai-undo').click();
      await expect(page.getByTestId('workflows-error')).toContainText('A newer change prevents Undo.');
      expect(undoCalls).toBe(2);
      expect((await readWorkflow()).current_version_id).toBe(manualVersion.current_version_id);
      expect((await readWorkflow()).description).toBe('Later manual version');
      expect(await page.evaluate(() => (window as typeof window & { __editStreamBodies: Array<Record<string, unknown>> }).__editStreamBodies.map(body => body.selected_workflow_id))).toEqual([original.id, original.id]);
    } finally {
      await page.request.delete(workflowUrl).catch(() => null);
    }
  });
});
