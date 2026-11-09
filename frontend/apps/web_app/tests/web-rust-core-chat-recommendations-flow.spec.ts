/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)
/**
 * Chat Recommendations card (replaced quick tips), VITE_OPENMATES_RUST_CORE=1 build.
 *
 * With the chat sidebar closed: a conference planning reply shows the Recommendations
 * card between the history and the follow-up chips with at least one memory and one
 * workflow, one dot per recommendation and working previous/next controls. A memory
 * recommendation opens an unsaved draft in Settings > Memories; only Save removes the
 * recommendation and adds the encrypted "Memory created: <title>" history event whose
 * link opens the memory. The state survives a reload. A workflow recommendation opens
 * the workflow side panel; Save adds "Workflow created: <title>". Dismiss removes the
 * last one for good, and with the setting off no card is shown.
 *
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 * Mock mode (E2E_USE_MOCKS): the chat_recommendations fixture provides the reply and
 * the recommendations; the billed create-draft call and the workflow authoring stream
 * are answered in the browser because CI runs no model.
 */
import type { Page, Route } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
  loginToTestAccount, sendMessage, setChatSidebarOpen, startNewChat, waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const {
  createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, withMockMarker
} = require('./signup-flow-helpers');

const USE_MOCKS = Boolean(process.env.E2E_USE_MOCKS);
const PROMPT = 'Help me plan my visit to an open source conference with talks, hallway time and rest.';
const RESPONSE_MARKER = 'Open source conference recommendations test';

type StreamWindow = typeof window & {
  __workflowStreamCases: unknown[][];
  __workflowStreamBodies: Array<Record<string, unknown>>;
};

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
    { id: 'message', type: 'send_chat_message', title: 'Send digest', config: { message: 'Conference digest' } }
  ],
  edges: [{ from: 'manual', to: 'message' }]
};

/** Draft-only authoring stream for the workflow side panel (same events as the server). */
function workflowDraftEvents(title: string): unknown[] {
  const sessionId = `recommendation-draft-${Date.now()}`;
  const previewWorkflow = { id: `preview-${sessionId}`, title, description: 'Weekly open source conference digest.', category: 'general_knowledge', status: 'draft', enabled: false, current_version_id: '', graph };
  return [
    { type: 'started', session_id: sessionId, status: 'running' },
    { type: 'progress', phase: 'planning' },
    { type: 'preview', workflow_index: 0, operation: 'create', provisional: true, validated: true, graph, metadata: { title }, accepted_node_count: 2, node: graph.nodes[1] },
    { type: 'session', session: { session_id: sessionId, status: 'draft', workflow: null, preview_workflow: previewWorkflow, assumptions: [] } }
  ];
}

function memoryDocument(title: string): string {
  return `---\ntitle: ${title}\nwhen_to_use: planning conference visits\nload_mode: ask_first\n---\n\nBalance talks, hallway conversations and rest breaks.\n`;
}

test.describe('chat recommendations', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
  test('card, memory and workflow saves, history events, reload, dismiss and setting off', async ({ page }: { page: Page }) => {
    test.setTimeout(300000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.setViewportSize({ width: 1280, height: 900 });
    const log = createSignupLogger('CHAT_RECOMMENDATIONS');
    const screenshot = createStepScreenshotter(log);

    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      const streamWindow = window as StreamWindow;
      streamWindow.__workflowStreamCases = [];
      streamWindow.__workflowStreamBodies = [];
      window.fetch = async (input, init) => {
        const events = String(input).includes('/v1/workflows/input/stream') ? streamWindow.__workflowStreamCases.shift() : undefined;
        if (!events) return originalFetch(input, init);
        streamWindow.__workflowStreamBodies.push(JSON.parse(String(init?.body ?? '{}')));
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            events.forEach((event, index) => setTimeout(() => {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
              if (index === events.length - 1) controller.close();
            }, index * 400));
          }
        });
        return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
      };
    });
    const createDraftBodies: Array<Record<string, unknown>> = [];
    if (USE_MOCKS) {
      await page.route('**/v1/memory-suggestions/create-draft', async (route: Route) => {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        createDraftBodies.push(body);
        const title = String(body.title);
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title, when_to_use: 'planning conference visits', body: memoryDocument(title) }) });
      });
    }

    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, screenshot);
    await setChatSidebarOpen(page, false, log);

    const card = page.getByTestId('recommendations-card');
    const item = page.getByTestId('recommendation-item');
    const notices = page.getByTestId('context-entry-event');
    const createdWorkflows: string[] = [];

    /** Pages forward until the visible recommendation has the kind. */
    // Shows the first "create" recommendation of a kind (Create opens a new draft;
    // Update opens the existing entry's preview instead).
    async function showKind(kind: 'memory' | 'workflow'): Promise<string> {
      const count = Number(await card.getAttribute('data-count'));
      for (let step = 0; step < count; step += 1) {
        if (await item.getAttribute('data-kind') === kind && await item.getAttribute('data-action') === 'create') {
          return (await page.getByTestId('recommendation-title').textContent())?.trim() ?? '';
        }
        await page.getByTestId('recommendation-next').click();
      }
      throw new Error(`No new ${kind} recommendation in the card`);
    }

    try {
      await startNewChat(page, log);
      await sendMessage(page, withMockMarker(`First write the exact phrase "${RESPONSE_MARKER}". ${PROMPT}`, 'chat_recommendations', 'fast'), log, screenshot, 'conference');
      const assistant = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
      if (USE_MOCKS) await expect(assistant).toContainText(RESPONSE_MARKER, { timeout: 60000 });
      const chatId = (await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id')) ?? '';
      expect(chatId).toMatch(/^[a-f0-9-]{36}$/);

      // Card: at least one memory and one workflow, one dot each, previous/next work.
      await expect(card).toBeVisible({ timeout: 90000 });
      const total = Number(await card.getAttribute('data-count'));
      expect(total).toBeGreaterThanOrEqual(2);
      if (USE_MOCKS) expect(total).toBe(3);
      await expect(page.getByTestId('recommendation-dot')).toHaveCount(total);
      await expect(card).toHaveAttribute('data-index', '0');
      const firstTitle = await page.getByTestId('recommendation-title').textContent();
      await page.getByTestId('recommendation-next').click();
      await expect(card).toHaveAttribute('data-index', '1');
      await expect(page.getByTestId('recommendation-dot').nth(1)).toHaveAttribute('aria-current', 'true');
      await expect(page.getByTestId('recommendation-title')).not.toHaveText(firstTitle ?? '');
      await page.getByTestId('recommendation-previous').click();
      await expect(card).toHaveAttribute('data-index', '0');
      await expect(page.getByTestId('recommendation-title')).toHaveText(firstTitle ?? '');
      await page.getByTestId('recommendation-previous').click();
      await expect(card).toHaveAttribute('data-index', String(total - 1));
      await expect(page.getByTestId('recommendation-embed').first()).toBeVisible();
      await screenshot(page, 'recommendations-card');
      const kinds = new Set<string>();
      for (let index = 0; index < total; index += 1) {
        kinds.add((await item.getAttribute('data-kind')) ?? '');
        await page.getByTestId('recommendation-next').click();
      }
      expect([...kinds].sort()).toEqual(['memory', 'workflow']);

      // Memory: Create opens an unsaved draft; the recommendation stays until Save.
      const memoryTitle = await showKind('memory');
      await page.getByTestId('recommendation-action').click();
      await expect(page.getByTestId('memory-draft-banner')).toBeVisible({ timeout: 60000 });
      await expect(page.getByTestId('rule-title')).toHaveValue(memoryTitle);
      if (USE_MOCKS) {
        expect(createDraftBodies).toHaveLength(1);
        expect(createDraftBodies[0]).toMatchObject({ chat_id: chatId, title: memoryTitle });
        expect(String(createDraftBodies[0].summary)).not.toBe('');
        expect(String(createDraftBodies[0].user_message)).toContain('open source conference');
        expect(String(createDraftBodies[0].assistant_response)).toContain(RESPONSE_MARKER);
      }
      await expect(card).toHaveAttribute('data-count', String(total));
      await page.getByTestId('rule-save').click();
      await expect(page.getByTestId('rule-saved-notice')).toBeVisible({ timeout: 20000 });
      await page.getByTestId('icon-button-close').click();
      await expect(card).toHaveAttribute('data-count', String(total - 1), { timeout: 20000 });
      const memoryNotice = page.locator('[data-testid="context-entry-event"][data-kind="memory"]');
      await expect(memoryNotice).toHaveCount(1, { timeout: 20000 });
      await expect(memoryNotice.getByTestId('context-entry-event-label')).toHaveText(`Memory created: ${memoryTitle}`);
      await screenshot(page, 'memory-created-notice');

      // The notice link opens the saved memory itself (no draft).
      await memoryNotice.getByTestId('context-entry-event-open').click();
      await expect(page.getByTestId('rule-title')).toHaveValue(memoryTitle, { timeout: 20000 });
      await expect(page.getByTestId('memory-draft-banner')).toHaveCount(0);
      await page.getByTestId('icon-button-close').click();

      // Reload: remaining recommendations and the history event persist.
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60000 });
      await expect(card).toHaveAttribute('data-count', String(total - 1), { timeout: 60000 });
      await expect(page.getByTestId('recommendation-title').filter({ hasText: memoryTitle })).toHaveCount(0);
      await expect(memoryNotice).toHaveCount(1, { timeout: 30000 });

      // Workflow: Create opens the side panel draft; Save adds the history event.
      const workflowTitle = await showKind('workflow');
      await page.evaluate((events) => { (window as StreamWindow).__workflowStreamCases.push(events); }, workflowDraftEvents(workflowTitle));
      await page.getByTestId('recommendation-action').click();
      const panel = page.getByTestId('workflow-side-panel');
      await expect(panel).toBeVisible({ timeout: 20000 });
      await expect.poll(() => page.evaluate(() => (window as StreamWindow).__workflowStreamBodies.length)).toBe(1);
      const streamBody = await page.evaluate(() => (window as StreamWindow).__workflowStreamBodies[0]);
      expect(streamBody).toMatchObject({ draft_only: true });
      expect(String(streamBody.text)).toContain(`Create a workflow: ${workflowTitle}`);
      await expect(page.getByTestId('workflow-side-panel-title')).toHaveValue(workflowTitle, { timeout: 20000 });
      await expect(card).toHaveAttribute('data-count', String(total - 1));
      const created = page.waitForResponse((response) => response.request().method() === 'POST' && /\/v1\/workflows$/.test(new URL(response.url()).pathname));
      await page.getByTestId('workflow-side-panel-save').click();
      const workflowId = (await (await created).json()).workflow.id as string;
      createdWorkflows.push(workflowId);
      await expect(panel).toHaveAttribute('data-saved', 'true', { timeout: 20000 });
      await page.getByTestId('workflow-side-panel-close').click();
      await expect(panel).toHaveCount(0);
      const workflowNotice = page.locator(`[data-testid="context-entry-event"][data-kind="workflow"][data-entry-id="${workflowId}"]`);
      await expect(workflowNotice).toHaveCount(1, { timeout: 20000 });
      await expect(workflowNotice.getByTestId('context-entry-event-label')).toHaveText(`Workflow created: ${workflowTitle}`);
      await expect(workflowNotice.getByTestId('context-entry-event-open')).toHaveAttribute('href', `/#workflow-id=${workflowId}&workflow-tab=details`);
      await expect(card).toHaveAttribute('data-count', String(total - 2), { timeout: 20000 });
      await screenshot(page, 'workflow-created-notice');

      // No dismiss control; saved entries stay removed and the rest remain after a reload.
      await expect(page.getByTestId('recommendation-dismiss')).toHaveCount(0);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60000 });
      await expect(notices).toHaveCount(2, { timeout: 60000 });
      if (total > 2) await expect(card).toHaveAttribute('data-count', String(total - 2), { timeout: 60000 });
      else await expect(card).toHaveCount(0, { timeout: 60000 });

      // Setting off: a new conference reply shows no card.
      await setRecommendationsSetting(page, false);
      await startNewChat(page, log);
      await sendMessage(page, withMockMarker(`First write the exact phrase "${RESPONSE_MARKER}". ${PROMPT}`, 'chat_recommendations', 'fast'), log, screenshot, 'setting-off');
      const offAssistant = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
      if (USE_MOCKS) await expect(offAssistant).toContainText(RESPONSE_MARKER, { timeout: 60000 });
      await expect(page.getByTestId('chat-header-summary')).not.toHaveText('', { timeout: 60000 });
      await expect(card).toHaveCount(0);
      await screenshot(page, 'setting-off-no-card');
    } finally {
      await setRecommendationsSetting(page, true).catch((error: unknown) => log(`Could not restore the setting: ${String(error)}`));
      for (const id of createdWorkflows) await page.request.delete(`${apiUrl()}/v1/workflows/${id}`).catch(() => null);
    }
  });
});

/** Settings > AI > Recommendations toggle; closes Settings afterwards. */
async function setRecommendationsSetting(page: Page, enabled: boolean): Promise<void> {
  await page.getByTestId('profile-container').click();
  const menu = page.locator('[data-testid="settings-menu"].visible');
  await expect(menu).toBeVisible({ timeout: 10000 });
  await menu.getByRole('menuitem', { name: /^AI$/i }).first().click();
  const row = page.getByTestId('ai-response-feature-recommendations');
  await expect(row).toBeVisible({ timeout: 10000 });
  const checkbox = row.locator('input[type="checkbox"]');
  if ((await checkbox.isChecked()) !== enabled) await row.click();
  await expect(checkbox).toBeChecked({ checked: enabled, timeout: 10000 });
  await page.getByTestId('icon-button-close').click();
}
