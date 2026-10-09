/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright login helpers expose CommonJS exports. */
/** Real scheduled completion dispatch, durable recovery and captured SMTP. */
import type { APIRequestContext, Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');

function apiUrl(): string {
  if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL;
  const host = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:3000');
  if (['localhost', '127.0.0.1'].includes(host.hostname)) return 'http://localhost:8000';
  throw new Error('The completion integration requires an explicit isolated API URL');
}

function probe(environment: Record<string, string>, marker: string): string {
  const envArgs = Object.entries(environment).flatMap(([key, value]) => ['-e', `${key}=${value}`]);
  const output = execFileSync('docker', [
    'compose', '-f', composeFile, 'exec', '-T', ...envArgs, 'api', 'python',
    '/app/backend/scripts/probe_workflow_completion_notification.py',
  ], { cwd: root, encoding: 'utf8', timeout: 90_000 });
  expect(output).toContain(marker);
  return output;
}

function scheduledGraph(at: string, skipMessage: boolean) {
  const trigger = { id: 'schedule', type: 'schedule_trigger', config: { schedule: { type: 'once', at } } };
  const send = { id: 'send', type: 'send_chat_message', config: {
    title: 'Scheduled completion chat', message: 'Scheduled notification integration result',
  } };
  const end = { id: 'end', type: 'end', config: {} };
  return skipMessage ? {
    version: 2, trigger_node_id: 'schedule', nodes: [trigger,
      { id: 'check', type: 'check', config: { mode: 'exact', predicate: { left: 1, op: 'eq', right: 2 } } },
      send, end,
    ], edges: [{ from: 'schedule', to: 'check' },
      { from: 'check', to: 'send', branch: 'yes' },
      { from: 'check', to: 'end', branch: 'no' }, { from: 'send', to: 'end' }],
  } : {
    version: 2, trigger_node_id: 'schedule', nodes: [trigger, send, end],
    edges: [{ from: 'schedule', to: 'send' }, { from: 'send', to: 'end' }],
  };
}

async function completedSchedule(request: APIRequestContext, workflowId: string): Promise<string> {
  let runId = '';
  await expect.poll(async () => {
    const response = await request.get(`${apiUrl()}/v1/workflows/${workflowId}/runs`);
    expect(response.ok(), await response.text()).toBe(true);
    const run = (await response.json()).runs.find((item: { trigger_type: string }) => item.trigger_type === 'schedule');
    if (run?.id) runId = run.id;
    return run?.status;
  }, { timeout: 240_000, intervals: [5_000] }).toBe('completed');
  return runId;
}

test.describe('Scheduled Workflow completion notifications on the isolated stack', () => {
  test.setTimeout(420_000);

  // contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery,notifications.workflow-run.chat-target,notifications.workflow-run.run-target,notifications.delivery.idempotent,notifications.content.privacy-boundary,workflows.execution.lifecycle-visible
  test('dispatches independent private completion channels with exact chat or run links', async ({ page }: { page: Page }) => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true'
      || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e'
      || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
    'Requires the runner-private product stack and Mailpit');
    const email = getTestAccount().email;
    expect(email).toMatch(/^ci-[a-z0-9+._-]+@example\.com$/);
    expect(existsSync(composeFile)).toBe(true);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);
    probe({ PROBE_EMAIL: email, PROBE_MODE: 'prepare' }, 'WORKFLOW_COMPLETION_NOTIFICATION_PROBE_PREPARED');
    const context = page.context();
    const request = context.request;
    const workflows: string[] = [];
    try {
      const at = new Date(Date.now() + 75_000).toISOString();
      for (const skipMessage of [false, true]) {
        const response = await request.post(`${apiUrl()}/v1/workflows`, { data: {
          title: `Private scheduled completion ${skipMessage ? 'no-send' : 'chat'} ${Date.now()}`,
          graph: scheduledGraph(at, skipMessage), enabled: true,
        } });
        expect(response.ok(), await response.text()).toBe(true);
        workflows.push((await response.json()).workflow.id);
      }
      // No owner device is connected when the scanner accepts and executes the
      // schedules. Completion email must not wait for chat delivery acknowledgement.
      await page.close();
      const [runId, noChatRunId] = await Promise.all(workflows.map((id) => completedSchedule(request, id)));
      const output = probe({ PROBE_EMAIL: email, WORKFLOW_ID: workflows[0], RUN_ID: runId,
        NO_CHAT_WORKFLOW_ID: workflows[1], NO_CHAT_RUN_ID: noChatRunId,
        PRUNE_RUN_CONTENT: '1',
      }, 'WORKFLOW_COMPLETION_NOTIFICATION_PROBE_OK');
      const linkLine = output.split('\n').find((line) => line.startsWith('WORKFLOW_COMPLETION_LINKS='));
      expect(linkLine, 'Probe must return the two real captured email links').toBeTruthy();
      const links = JSON.parse(linkLine!.slice('WORKFLOW_COMPLETION_LINKS='.length)) as { chat: string; run: string };
      const detailResponse = await request.get(`${apiUrl()}/v1/workflows/${workflows[0]}/runs/${runId}`);
      expect(detailResponse.ok(), await detailResponse.text()).toBe(true);
      const retainedRun = (await detailResponse.json()).run;
      expect(retainedRun.content_available).toBe(false);
      expect(retainedRun.completion_notification?.chat_id).toBeTruthy();
      const reopened = await context.newPage();
      await reopened.goto(getE2EDebugUrl(links.chat), { waitUntil: 'domcontentloaded' });
      await expect(reopened.getByTestId('active-chat-container')).toHaveAttribute(
        'data-current-chat-id', retainedRun.completion_notification.chat_id, { timeout: 45_000 },
      );
      await expect(reopened.getByTestId('message-assistant').filter({ hasText: 'Scheduled notification integration result' })).toBeVisible();
      await reopened.goto(getE2EDebugUrl(links.run), { waitUntil: 'domcontentloaded' });
      await expect(reopened.getByTestId('workflow-run-selector').locator('select')).toHaveValue(noChatRunId, { timeout: 30_000 });
      await expect(reopened.locator(`[data-testid="workflow-run-marker"][data-run-id="${noChatRunId}"]`)).toHaveAttribute('aria-pressed', 'true');
      await expect(reopened.getByTestId('workflow-run-detail')).toBeVisible();
    } finally {
      for (const id of workflows) await request.delete(`${apiUrl()}/v1/workflows/${id}`);
    }
  });
});
