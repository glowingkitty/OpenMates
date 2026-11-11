/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflow editor opened from a chat (chat Recommendations), VITE_OPENMATES_RUST_CORE=1 build.
 *
 * A workflow recommendation opens the regular workflow editor (WorkflowChatPane)
 * in the chat: chat column left (400px) and editor right at 1280px, covering the
 * (inert) chat at 390px. The draft is generated through the draft-only authoring
 * stream (body draft_only: true; the stream is a fixture so no model runs) and
 * shown in the regular draft editor; nothing is persisted until Save
 * (workflow-save-draft). Save reports exactly one saved event and switches the
 * same pane to the saved workflow, where it can be enabled and tested in place.
 * Closing unsaved work asks first, the chat-history deep link (update + empty
 * instruction) only shows the saved workflow, a request for another chat closes
 * the editor, and closing returns to the chat at the same scroll position.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const BOTH = ['web-laptop', 'web-phone'];

const WORKFLOW_SIDE_PANEL_PROOF = defineVideoProof({
  id: 'web-rust-core-workflow-side-panel',
  title: 'A workflow recommendation opens the regular workflow editor beside the chat',
  surface: 'web',
  devices: BOTH,
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'draft-generating', text: 'Choosing a workflow recommendation opens the workflow editor to the right of the chat and generates the draft visibly.', checkpoint: 'draft-generating', devices: BOTH },
    { id: 'draft-saved', text: 'Nothing is saved until Save; after saving, the same editor shows the saved workflow, ready to enable and test.', checkpoint: 'draft-saved', devices: BOTH },
    { id: 'mobile-fullscreen', text: 'On a phone the saved workflow opens in the regular editor over the chat with a close control.', checkpoint: 'mobile-fullscreen', devices: BOTH }
  ],
  assertions: [
    { id: 'draft-generating.assertion', checkpoint: 'draft-generating', visual: 'The 400px chat column is on the left and the regular workflow header with the AI draft preview and a Stop control is on the right.', devices: BOTH },
    { id: 'draft-saved.assertion', checkpoint: 'draft-saved', visual: 'The regular workflow header shows the saved name with the on/off toggle and tabs, and the editable workflow graph with Test now stays visible beside the chat.', devices: BOTH },
    { id: 'mobile-fullscreen.assertion', checkpoint: 'mobile-fullscreen', visual: 'The regular workflow editor covers the full phone width with its name and a close control, and no AI generation runs.', devices: BOTH }
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

type PanelRequest = { chatId: string; recommendationId: string; mode: 'create' | 'update'; workflowId: string | null; instruction: string };
type SavedEvent = { chatId: string; recommendationId: string; workflowId: string; title: string; action: 'created' | 'updated' };
type StreamWindow = typeof window & {
  __workflowStreamCases: unknown[][];
  __workflowStreamBodies: Array<Record<string, unknown>>;
  __openmatesE2EWorkflowSidePanel?: { open: (request: PanelRequest) => void; close: () => void; savedEvents: SavedEvent[] };
};

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : `${url.protocol}//api.${url.hostname.replace(/^app\./, '')}`;
}

// A scheduled graph with a notification: ready to enable and to test in the saved editor.
const graph = {
  version: 2, trigger_node_id: 'schedule',
  nodes: [
    { id: 'schedule', type: 'schedule_trigger', title: 'Daily start', config: { schedule: { type: 'daily', time: '09:00', timezone: 'UTC' } } },
    { id: 'notify', type: 'send_chat_message', title: 'Send report', config: { title: 'Conference digest', message: 'Conference summary' } }
  ],
  edges: [{ from: 'schedule', to: 'notify' }]
};

/** Scroll offset of the chat history (the element the user scrolls). */
function chatScrollTop(page: Page): Promise<number> {
  return page.getByTestId('chat-pane').getByTestId('chat-history-container').evaluate((element: HTMLElement) => Math.round(element.scrollTop));
}

/** Scroll the chat history half way (when it can scroll) and return the settled offset. */
async function scrollChatToMiddle(page: Page): Promise<number> {
  const history = page.getByTestId('chat-pane').getByTestId('chat-history-container');
  await expect(history).toHaveAttribute('data-scroll-state', 'ready', { timeout: 20000 });
  await history.evaluate((element: HTMLElement) => { element.scrollTop = Math.floor((element.scrollHeight - element.clientHeight) / 2); });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  return chatScrollTop(page);
}

function draftEvents(sessionId: string, title: string): unknown[] {
  const previewWorkflow = { id: `preview-${sessionId}`, title, description: 'Weekly open source conference digest.', category: 'general_knowledge', status: 'draft', enabled: false, current_version_id: '', graph };
  return [
    { type: 'started', session_id: sessionId, status: 'running' },
    { type: 'progress', phase: 'planning' },
    {
      type: 'preview', workflow_index: 0, operation: 'create', provisional: true, validated: true,
      graph: { ...graph, nodes: graph.nodes.slice(0, 1), edges: [] }, metadata: { title }, accepted_node_count: 1, node: graph.nodes[0]
    },
    { type: 'progress', phase: 'preview' },
    { type: 'session', session: { session_id: sessionId, status: 'draft', workflow: null, preview_workflow: previewWorkflow, assumptions: [] } }
  ];
}

test.describe('chat workflow editor', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor,workflows-ui.chat-pane.regular-editor
  test('generates an unsaved draft in the regular editor beside the chat, saves once, guards unsaved close, keeps the chat scroll and covers the chat on mobile', async ({ page }: { page: Page }, testInfo: TestInfo) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      const streamWindow = window as StreamWindow;
      streamWindow.__workflowStreamCases = [];
      streamWindow.__workflowStreamBodies = [];
      window.fetch = async (input, init) => {
        if (!String(input).includes('/v1/workflows/input/stream')) return originalFetch(input, init);
        const events = streamWindow.__workflowStreamCases.shift();
        if (!events) throw new Error('Missing workflow stream scenario');
        streamWindow.__workflowStreamBodies.push(JSON.parse(String(init?.body ?? '{}')));
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true });
            events.forEach((event, index) => setTimeout(() => {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
              if (index === events.length - 1) controller.close();
            }, index * 600));
          }
        });
        return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
      };
    });
    const log = (message: string) => console.log(`[WORKFLOW_SIDE_PANEL_E2E] ${message}`);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, async () => {});
    await expect.poll(() => page.evaluate(() => Boolean((window as StreamWindow).__openmatesE2EWorkflowSidePanel))).toBe(true);
    const chatId = (await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id')) ?? '';
    const panel = page.getByTestId('workflow-chat-pane');
    const closePane = () => panel.getByTestId('workflow-detail-back').click();
    const created: string[] = [];
    const queue = (events: unknown[]) => page.evaluate((scenario) => { (window as StreamWindow).__workflowStreamCases.push(scenario); }, events);
    const open = (request: PanelRequest) => page.evaluate((value) => (window as StreamWindow).__openmatesE2EWorkflowSidePanel?.open(value), request);
    const savedEvents = () => page.evaluate(() => (window as StreamWindow).__openmatesE2EWorkflowSidePanel?.savedEvents ?? []);
    const streamBodies = () => page.evaluate(() => (window as StreamWindow).__workflowStreamBodies);
    const title = `Conference digest ${Date.now()}`;
    const proof = IS_PROOF_CAPTURE
      ? createVideoProofRuntime(WORKFLOW_SIDE_PANEL_PROOF, { device: PROOF_DEVICE, attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }) })
      : null;
    const step = async (id: string, check: () => Promise<void>) => {
      if (proof) await proof.assert(`${id}.assertion`, check);
      else await check();
      if (proof) await proof.checkpoint(id);
    };

    try {
      // 1280px: chat left (400px), editor right; the AI draft is generated visibly and nothing is saved.
      await queue(draftEvents('panel-draft-1', title));
      await open({ chatId, recommendationId: 'rec-w1', mode: 'create', workflowId: null, instruction: 'Send me a weekly open source conference digest' });
      await step('draft-generating', async () => {
        await expect(panel).toBeVisible();
        await expect(panel).toHaveAttribute('data-layout', 'side');
        await expect(panel).toHaveAttribute('data-state', 'authoring');
        await expect(panel.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'provisional');
        await expect(page.getByTestId('workflow-ai-pending')).toBeVisible();
        await expect(page.getByTestId('workflow-ai-stop')).toBeVisible();
        await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
      });
      await expect.poll(async () => (await streamBodies()).length).toBe(1);
      expect((await streamBodies())[0]).toMatchObject({ draft_only: true, text: 'Send me a weekly open source conference digest' });
      await expect(page.getByTestId('chat-pane')).toHaveAttribute('data-split-layout', 'split');
      const chatBox = await page.getByTestId('chat-pane').boundingBox();
      const panelBox = await page.getByTestId('workflow-chat-pane-container').boundingBox();
      expect(chatBox && panelBox).toBeTruthy();
      expect(Math.round(chatBox!.width)).toBeGreaterThanOrEqual(395);
      expect(Math.round(chatBox!.width)).toBeLessThanOrEqual(405);
      expect(chatBox!.x + chatBox!.width).toBeLessThanOrEqual(panelBox!.x + 1);
      expect(panelBox!.width).toBeGreaterThan(500);

      await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0, { timeout: 15000 });
      await expect(panel).toHaveAttribute('data-state', 'draft');
      await expect(panel.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'draft');
      await expect(page.getByTestId('workflow-editor')).toBeVisible();
      await expect(page.getByTestId('workflow-draft-title-input')).toHaveValue(title);
      await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
      expect(await savedEvents()).toEqual([]);

      // Save persists once, reports exactly one saved event and shows the saved workflow in the same editor.
      const save = page.getByTestId('workflow-save-draft');
      await expect(save).toBeEnabled();
      const createResponse = page.waitForResponse((response) => response.request().method() === 'POST' && /\/v1\/workflows$/.test(new URL(response.url()).pathname));
      await save.click();
      const createdWorkflow = (await (await createResponse).json()).workflow;
      created.push(createdWorkflow.id);
      await step('draft-saved', async () => {
        await expect(panel).toHaveAttribute('data-state', 'saved');
        await expect(panel.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'saved');
        await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
        await expect(save).toHaveCount(0);
        await expect(page.getByTestId('workflow-view-tabs')).toBeVisible();
        await expect(page.getByTestId('workflow-editor')).toBeVisible();
        await expect(page.getByTestId('workflow-template-test-now')).toBeVisible();
      });
      await expect.poll(savedEvents).toEqual([{ chatId, recommendationId: 'rec-w1', workflowId: createdWorkflow.id, title, action: 'created' }]);
      // The saved workflow is enabled and paused again in place, without leaving the chat.
      const toggle = page.getByTestId('toggle-workflow');
      await expect(toggle).toBeEnabled({ timeout: 20000 });
      await toggle.click();
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'true', { timeout: 20000 });
      await toggle.click();
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false', { timeout: 20000 });
      await expect(panel).toBeVisible();
      expect(await savedEvents()).toHaveLength(1);

      // Closing a saved workflow needs no confirmation.
      await closePane();
      await expect(panel).toHaveCount(0);
      await expect(page.getByTestId('chat-pane')).toHaveAttribute('data-split-layout', 'full');

      // Closing an unsaved draft asks first: Stay keeps it, Discard drops it without saving.
      // Closing returns to the chat at the scroll offset it had when the editor opened.
      const splitScrollTop = await scrollChatToMiddle(page);
      await queue(draftEvents('panel-draft-2', `${title} copy`));
      await open({ chatId, recommendationId: 'rec-w2', mode: 'create', workflowId: null, instruction: 'Another digest' });
      await expect(page.getByTestId('workflow-draft-title-input')).toHaveValue(`${title} copy`, { timeout: 15000 });
      await expect(page.getByTestId('chat-pane')).toHaveAttribute('data-split-layout', 'split');
      await closePane();
      await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
      await page.getByTestId('workflow-guard-stay').click();
      await expect(page.getByTestId('workflow-unsaved-guard')).toHaveCount(0);
      await expect(panel).toBeVisible();
      await closePane();
      await page.getByTestId('workflow-guard-discard').click();
      await expect(panel).toHaveCount(0);
      await expect(page.getByTestId('chat-pane')).toHaveAttribute('data-split-layout', 'full');
      await expect.poll(() => chatScrollTop(page)).toBe(splitScrollTop);
      expect(await savedEvents()).toHaveLength(1);

      // A request for another chat closes the panel.
      await open({ chatId: `${chatId}-other`, recommendationId: 'rec-w3', mode: 'update', workflowId: createdWorkflow.id, instruction: '' });
      await expect(panel).toHaveCount(0);

      // 390px deep link (update + empty instruction): covers the inert chat, shows the saved workflow, starts no authoring.
      await page.setViewportSize({ width: 390, height: 844 });
      const mobileScrollTop = await scrollChatToMiddle(page);
      await open({ chatId, recommendationId: 'rec-w1', mode: 'update', workflowId: createdWorkflow.id, instruction: '' });
      await step('mobile-fullscreen', async () => {
        await expect(panel).toBeVisible();
        await expect(panel).toHaveAttribute('data-layout', 'fullscreen');
        await expect(panel).toHaveAttribute('data-state', 'saved');
        await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
        await expect(page.getByTestId('workflow-editor')).toBeVisible();
        await expect(page.getByTestId('workflow-ai-pending')).toHaveCount(0);
      });
      await expect(page.getByTestId('chat-pane')).toHaveAttribute('inert', '');
      const mobileBox = await page.getByTestId('workflow-chat-pane-container').boundingBox();
      expect(mobileBox!.width).toBeGreaterThanOrEqual(360);
      expect(await streamBodies()).toHaveLength(2);
      await closePane();
      await expect(panel).toHaveCount(0);
      await expect(page.getByTestId('chat-pane')).not.toHaveAttribute('inert', '');
      await expect.poll(() => chatScrollTop(page)).toBe(mobileScrollTop);
      expect(await savedEvents()).toHaveLength(1);
      if (proof) await proof.attach();
    } finally {
      for (const id of created) await page.request.delete(`${apiUrl()}/v1/workflows/${id}`).catch(() => null);
    }
  });
});
