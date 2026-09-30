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
  test('renders fragmented provisional graphs, clears rejection, and opens committed results', async ({ page }: { page: Page }) => {
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
    const seed = async (title: string) => {
      const response = await page.request.post(`${apiUrl()}/v1/workflows`, { data: { title, graph, enabled: false } });
      expect(response.ok(), await response.text()).toBe(true);
      const workflow = (await response.json()).workflow;
      created.push(workflow.id);
      return workflow;
    };
    try {
      const one = await seed(`Stream one ${Date.now()}`);
      const two = await seed(`Stream two ${Date.now()}`);
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflow-input-textarea')).toBeVisible();
      let provisionalFetches = 0;
      page.on('request', request => { if (/\/v1\/workflows\/provisional-/.test(request.url())) provisionalFetches += 1; });
      const configure = (events: unknown[], holdOpen = false, holdResponse = false) => page.evaluate(({ events, holdOpen, holdResponse }) => {
        (window as typeof window & { __workflowStreamCases: Array<{ events: unknown[]; holdOpen?: boolean; holdResponse?: boolean }> }).__workflowStreamCases.push({ events, holdOpen, holdResponse });
      }, { events, holdOpen, holdResponse });
      const preview = (workflow: { id: string; title: string }, index: number, accepted = 2) => ({
        type: 'preview', workflow_index: index, operation: 'create',
        graph: { ...graph, nodes: graph.nodes.slice(0, accepted), edges: accepted > 1 ? graph.edges : [] },
        metadata: { title: workflow.title }, accepted_node_count: accepted,
        node: graph.nodes[accepted - 1], provisional: true, validated: true
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
      const singleHeader = { ...preview(one, 0, 1), accepted_node_count: 0, metadata: { title: one.title, description: 'A draft with validated steps' } };
      await page.evaluate((event) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      }, singleHeader);
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(one.title);
      await expect(page.getByTestId('workspace-detail-description')).toHaveText('A draft with validated steps');
      await expect(page.getByTestId('workflow-ai-pending-preview').getByTestId('workflow-node-card')).toHaveCount(1);
      await expect(page.getByTestId('workflow-ai-accepted-nodes')).toHaveCount(0);
      await page.evaluate((event) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      }, { ...preview(one, 0, 2), accepted_node_count: 1, metadata: singleHeader.metadata });
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
      expect(provisionalFetches).toBe(0);
      await page.evaluate((one) => {
        const stream = (window as typeof window & { __workflowOpenStream?: ReadableStreamDefaultController<Uint8Array> }).__workflowOpenStream;
        if (!stream) throw new Error('Pending workflow stream was not opened');
        stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: 'progress', phase: 'saving' })}\n\ndata: ${JSON.stringify({ type: 'session', session: { session_id: 'single-stream', status: 'executed', workflows: [one], mutations: [{ type: 'create_workflow', target_id: one.id }] } })}\n\n`));
        stream.close();
      }, one);
      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
      await expect(page.getByTestId('workflow-ai-edit-textarea')).toBeEnabled();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(one.title);
      await page.getByTestId('workflow-detail-back').click();

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
});
