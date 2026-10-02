/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=non_visual_email_delivery
/** Signed-in destinations for the chat, Workflow run, and settings URLs in notification emails. */
export {};

import { randomUUID } from 'node:crypto';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const { email, password, otpKey } = getTestAccount();

function apiUrl(): string {
  if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL;
  const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  if (base.hostname === 'localhost' || base.hostname === '127.0.0.1') return 'http://localhost:8000';
  if (!base.hostname.startsWith('app.')) throw new Error('Set PLAYWRIGHT_TEST_API_URL for this test target');
  return `${base.protocol}//api.${base.hostname.slice(4)}`;
}

function noInferenceGraph() {
  return {
    version: 1,
    trigger_node_id: 'schedule',
    nodes: [
      { id: 'schedule', type: 'schedule_trigger', title: 'Daily start', config: { schedule: { type: 'daily', time: '09:00', timezone: 'UTC' } } },
      { id: 'approval', type: 'ask_user', title: 'Wait for approval', config: { prompt: 'Continue?', timeout_seconds: 600 } },
      { id: 'notify', type: 'send_notification', title: 'Show result', config: { title: 'Ready', body: 'Ready' } },
      { id: 'end', type: 'end', title: 'Done', config: {} }
    ],
    edges: [
      { from: 'schedule', to: 'approval' },
      { from: 'approval', to: 'notify' },
      { from: 'notify', to: 'end' }
    ]
  };
}

test.describe('Notification email destinations', () => {
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: supporting surface=gui.web assertions=notifications.surface.semantic-parity,chat-navigation.open.local-first-coherent,workflows.execution.lifecycle-visible
  test('opens populated signed-in chat and exact Workflow run links', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);

    // This browser-local fixture exercises the signed-in link destination. The
    // separate Mailpit probes check the actual email HTML and server delivery.
    const chatId = `e2e-email-link-${randomUUID()}`;
    const message = 'Notification link destination is populated.';
    await page.evaluate(async ({ chatId, message }) => {
      const seed = (window as Window & {
        __openmatesE2ESeedChat?: (input: {
          chat: Record<string, unknown>;
          messages: Record<string, unknown>[];
        }) => Promise<unknown>;
      }).__openmatesE2ESeedChat;
      if (!seed) throw new Error('E2E chat seed helper is unavailable');
      const now = Math.floor(Date.now() / 1000);
      await seed({
        chat: {
          chat_id: chatId, title: 'Notification link destination', messages_v: 1, title_v: 1,
          last_edited_overall_timestamp: now, created_at: now, updated_at: now
        },
        messages: [{
          message_id: `e2e-email-link-message-${chatId}`, chat_id: chatId,
          role: 'assistant', created_at: now, status: 'synced', content: message
        }]
      });
    }, { chatId, message });

    await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 30_000 });
    await expect(page.getByTestId('message-assistant').filter({ hasText: message })).toBeVisible();

    await page.goto(getE2EDebugUrl('/#settings/notifications/chat'), { waitUntil: 'domcontentloaded' });
    const settings = page.getByTestId('settings-menu');
    await expect(settings).toBeVisible({ timeout: 20_000 });
    await expect(settings).toHaveAttribute('data-active-view', 'notifications/chat');
    await expect(settings.getByTestId('email-section')).toBeVisible();

    let workflowId: string | null = null;
    try {
      const created = await page.request.post(`${apiUrl()}/v1/workflows`, {
        data: { title: `Notification link ${randomUUID()}`, graph: noInferenceGraph(), enabled: true }
      });
      expect(created.ok(), await created.text()).toBe(true);
      workflowId = (await created.json()).workflow.id;
      const started = await page.request.post(`${apiUrl()}/v1/workflows/${workflowId}/run`, {
        data: { mode: 'test', input: {} },
        headers: { 'Idempotency-Key': `${workflowId}-notification-link` }
      });
      expect(started.ok(), await started.text()).toBe(true);
      const runId = (await started.json()).run.id;

      await page.goto(getE2EDebugUrl(`/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=runs&run-id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflow-run-selector').locator('select')).toHaveValue(runId, { timeout: 30_000 });
      const selectedRun = page.locator(`[data-testid="workflow-run-marker"][data-run-id="${runId}"]`);
      await expect(selectedRun).toBeVisible();
      await expect(selectedRun).toHaveAttribute('aria-pressed', 'true');
      await expect(selectedRun).toHaveAttribute('data-run-status', /^(queued|running|waiting|completed)$/);
      await expect(page.getByTestId('workflow-run-detail')).toBeVisible();
    } finally {
      if (workflowId) {
        const deleted = await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`);
        expect(deleted.ok(), await deleted.text()).toBe(true);
      }
    }
  });
});
