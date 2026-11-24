/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Real-inference web proof of Tasks as inline embeds.
 *
 * The assistant creates a Task by writing a task block (no tool call, no system event),
 * edits its due date with a versioned diff, and a later search lists it. The card shows
 * the task icon, title, due date and status, never a raw id. Runs in the `real_inference`
 * CI group (isolated per-run stack, no mocks).
 */
export {};

import type { Page } from '@playwright/test';
import { observeTaskJobPersistence } from './helpers/task-job-proof';

const { test, expect } = require('./helpers/cookie-audit');
const {
  deleteActiveChat, focusMessageEditor, loginToTestAccount, startNewChat, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'task-inline-embeds-web-real',
  title: 'The assistant creates, edits and finds a Task through inline task cards',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'created', text: 'The reply shows one task card with title, due date and status.', checkpoint: '01-task-created', devices: ['web-laptop'] },
    { id: 'edited', text: 'Moving the task changes the same card and adds a version.', checkpoint: '02-task-edited', devices: ['web-laptop'] },
    { id: 'undo', text: 'Undo returns the original due date.', checkpoint: '03-undo', devices: ['web-laptop'] },
    { id: 'search', text: 'A task search lists the task.', checkpoint: '04-task-search', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'task_inline.created', checkpoint: '01-task-created', visual: 'One task card with the title, "Nov 24" and a status; no system message and no raw id.', devices: ['web-laptop'] },
    { id: 'task_inline.edited', checkpoint: '02-task-edited', visual: 'The task card shows "Nov 27" and the fullscreen timeline lists two versions.', devices: ['web-laptop'] },
    { id: 'task_inline.undo', checkpoint: '03-undo', visual: 'After Undo the task card shows "Nov 24" again.', devices: ['web-laptop'] },
    { id: 'task_inline.search', checkpoint: '04-task-search', visual: 'The tasks search result lists the task title.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const TURN_TIMEOUT = 300_000;
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;
const TITLE = /Three minutes by an open window/i;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const CARD = '[data-testid="task-embed-card"]';

let proof: { checkpoint(id: string): Promise<void> } | null = null;

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await proof?.checkpoint(name);
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

/** Waits until the chat WebSocket is connected and the initial sync finished, so a send is admitted. */
async function waitForChatConnection(page: Page): Promise<void> {
  await expect.poll(async () => page.evaluate(async () => {
    const state = await (window as any).__openmatesE2EChatConnectionState?.();
    return Boolean(state?.websocketConnected && state?.contextSyncCompleted);
  }), { timeout: 60_000, intervals: [500] }).toBe(true);
}

async function sendWithModel(page: Page, prompt: string, kind: string): Promise<void> {
  await waitForChatConnection(page);
  await focusMessageEditor(page.getByTestId('message-editor'));
  await page.keyboard.insertText(`@${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
    .toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
  // Same send path as real-inference-gemini-chat.spec.ts: type, close suggestions, click Send.
  const userMessages = page.getByTestId('message-user');
  const usersBefore = await userMessages.count();
  await page.keyboard.insertText(` ${prompt}`);
  await page.keyboard.press('Escape');
  await page.locator('[data-action="send-message"]').click();
  await expect(userMessages).toHaveCount(usersBefore + 1, { timeout: 60_000 });
  await expect(userMessages.last()).toHaveAttribute('data-status', /^(sent|delivered)$/, { timeout: 60_000 });
  await expect(page.getByTestId('message-editor')).not.toContainText(prompt.slice(0, 24));
  console.log(`[TASK_INLINE] sent ${kind} turn`);
}

async function waitForTurn(page: Page, assistantsBefore: number): Promise<void> {
  await expect.poll(() => page.getByTestId('message-assistant').count(), { timeout: TURN_TIMEOUT, intervals: [2_000] })
    .toBeGreaterThan(assistantsBefore);
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
  await expect(busy).toHaveCount(0, { timeout: TURN_TIMEOUT });
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

async function expectNoSystemEventOrRawId(page: Page): Promise<void> {
  await expect(page.getByTestId('system-message-text').filter({ hasText: / created\b/ })).toHaveCount(0);
  const history = (await page.getByTestId('active-chat-container').innerText()) ?? '';
  expect(history, 'no raw id is shown in the chat history').not.toMatch(UUID);
}

test.describe('Tasks as inline embeds: create, edit with versions, search (real inference)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireRealInference('Real-inference inline task embeds proof', BASE_URL);
  });

  // contract-test: direct surface=gui.web assertions=task-inline.create.fence-not-tool,task-inline.edit.diff-versioned,task-inline.presentation.no-raw-ids
  test('creates a task card, edits it with versions and undo, then finds it by search', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_500_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await skipIfFeaturesDisabled(test, page, ['platform:tasks']);
    const committedTasks = observeTaskJobPersistence(page);
    await loginToTestAccount(page);
    await startNewChat(page);

    const activeChat = page.getByTestId('active-chat-container');
    const savedTaskIds = async () => committedTasks((await activeChat.getAttribute('data-current-chat-id')) ?? '');

    // a. Create
    let assistants = await page.getByTestId('message-assistant').count();
    await sendWithModel(page, 'Create a task for me: Three minutes by an open window, due 2026-11-24.', 'task-inline-create');
    await waitForTurn(page, assistants);
    const card = page.locator(CARD);
    await expect(card).toHaveCount(1, { timeout: 60_000 });
    await expect.poll(savedTaskIds, { timeout: 45_000 }).toHaveLength(1);
    const [taskId] = await savedTaskIds();
    await expect(card.getByTestId('task-embed-title')).toContainText(TITLE);
    await expect(card.getByTestId('task-embed-due-date')).toContainText('Nov 24');
    await expect(card.getByTestId('task-embed-status')).toBeVisible();
    // The card's header corner shows the task icon, not a blank square.
    const cornerMask = await page.locator('[data-testid="embed-preview"]', { has: card }).last().locator('.result-corner > span').first()
      .evaluate((el) => getComputedStyle(el).maskImage || getComputedStyle(el).webkitMaskImage);
    // task.svg by file name, or inlined by Vite as a data URL with its checklist path.
	expect(/task\.svg/.test(cornerMask) || decodeURIComponent(cornerMask).includes('M12.142 1L5.504 7.677')).toBe(true);
    await expectNoSystemEventOrRawId(page);
    await card.scrollIntoViewIfNeeded();
    await shot(page, testInfo, '01-task-created');

    // b. Edit: same card moves to Nov 27, fullscreen timeline has two versions
    assistants = await page.getByTestId('message-assistant').count();
    await sendWithModel(page, 'Move that task to Friday 2026-11-27.', 'task-inline-edit');
    await waitForTurn(page, assistants);
    await expect(card.last().getByTestId('task-embed-due-date')).toContainText('Nov 27', { timeout: 60_000 });
    await expect.poll(savedTaskIds, { timeout: 45_000 }).toEqual([taskId, taskId]);
    await expect(card.last().getByTestId('task-embed-title')).toContainText(TITLE);
    await card.last().click();
    const fullscreen = page.getByTestId('task-embed-fullscreen-content');
    await expect(fullscreen).toBeVisible({ timeout: 30_000 });
    const timeline = page.getByTestId('embed-version-timeline');
    await expect(timeline).toBeVisible({ timeout: 30_000 });
    await expect(timeline.locator('[data-testid^="version-dot-"]')).toHaveCount(2, { timeout: 30_000 });
    await shot(page, testInfo, '02-task-edited');

    // Undo: confirm the first version and wait for the new revision before closing.
    await timeline.getByTestId('version-dot-1').click();
    const restore = timeline.getByTestId('restore-version-btn');
    await expect(restore).toBeEnabled();
    await restore.click();
    await expect(restore).toHaveText('Confirm restore v1');
    const restored = page.waitForResponse((response) =>
      response.request().method() === 'PATCH' &&
      new URL(response.url()).pathname === `/v1/user-tasks/${taskId}` && response.ok(),
    );
    await restore.click();
    expect((await (await restored).json()).task.version).toBe(3);
    await expect(timeline.getByTestId('version-dot-3')).toBeVisible({ timeout: 30_000 });
    await page.keyboard.press('Escape');
    await expect(card.last().getByTestId('task-embed-due-date')).toContainText('Nov 24', { timeout: 30_000 });
    await shot(page, testInfo, '03-undo');
    await expectNoSystemEventOrRawId(page);

    // c. Search lists the task
    assistants = await page.getByTestId('message-assistant').count();
    await sendWithModel(page, 'Search my tasks for open window.', 'task-inline-search');
    await waitForTurn(page, assistants);
    const results = page.getByTestId('message-assistant').last()
      .locator('[data-testid="embed-preview"][data-app-id="tasks"][data-skill-id="search"][data-status="finished"]')
      .first();
    await expect(results.getByTestId('task-search-embed-preview')).toContainText(/Found \d+ tasks?/, { timeout: 120_000 });
    await results.getByTestId('result-preview-expand').click();
    await expect(page.getByTestId('search-template-grid').getByTestId('task-embed-title').filter({ hasText: TITLE })).toBeVisible();
    await shot(page, testInfo, '04-task-search');
    await page.keyboard.press('Escape');
    await deleteActiveChat(page);
  });
});
