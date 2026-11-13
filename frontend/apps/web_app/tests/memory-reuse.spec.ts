/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and attached screenshots cover each checkpoint)
/**
 * Assistant Memory reuse across chats, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Chat 1: the assistant saves a personal Memory "Career profile" (ask-first load mode).
 * Chat 2: a later question needs it, the server asks to load it, the permission dialog
 * names "Career profile", and after the user clicks include the answer uses the Memory
 * ("Example Retail GmbH"). The Memory is removed through Undo at the end.
 *
 * Mocked (E2E_USE_MOCKS): only the model's choice of which Memory to request and the
 * reply texts (fixtures memory_reuse_save and memory_reuse_load). The catalog sent by the
 * browser, the server request, the dialog, the approval and the continuation are real.
 * Without mocks (dev-only proof: scripts/memory_reuse_web_real_test.py) the model itself
 * decides to save and to request the Memory; the prompts then carry the fact to remember.
 */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
  loginToTestAccount, sendMessage, setChatSidebarOpen, startNewChat, waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const {
  createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, withMockMarker
} = require('./signup-flow-helpers');

const MOCKED = Boolean(process.env.E2E_USE_MOCKS);
const TITLE = 'Career profile';
const SAVE_PROMPT = MOCKED
  ? 'Please remember my career profile for later.'
  : `Save a memory titled "${TITLE}" for my job applications: I work as a sales lead at Example Retail GmbH. Ask me before using it in later chats.`;
const LOAD_PROMPT = MOCKED
  ? 'Which employer should I mention in my cover letter?'
  : 'Which employer should I mention in my cover letter? Use my saved career profile memory.';

const NOTICE = '[data-testid="context-entry-event"][data-kind="memory"][data-source="assistant"]';

/** Opens Settings > Memories and returns the private Memory rows titled TITLE. */
async function leftoverMemoryRows(page: Page) {
  await page.getByTestId('profile-container').click();
  const menu = page.locator('[data-testid="settings-menu"].visible');
  await expect(menu).toBeVisible({ timeout: 10000 });
  await menu.getByRole('menuitem', { name: /^Memories$/i }).first().click();
  const editor = page.locator('[data-testid="memories-editor"][data-source="personal"]');
  await expect(editor).toBeVisible({ timeout: 20000 });
  return editor.getByTestId('memory-row').filter({ hasText: TITLE });
}

test.describe('assistant memory reuse', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
  test('a saved Memory is requested in a new chat, approved in the dialog and used in the answer', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(300000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    const log = createSignupLogger('MEMORY_REUSE');
    const screenshot = createStepScreenshotter(log);

    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, screenshot);
    await setChatSidebarOpen(page, false, log);

    // A leftover Memory from an aborted run would make the dialog ambiguous: fail early.
    const leftovers = await leftoverMemoryRows(page);
    expect(await leftovers.count(), `Leftover "${TITLE}" Memory from an aborted run; delete it in Settings > Memories`).toBe(0);
    await page.getByTestId('icon-button-close').click();

    // Chat 1: the assistant saves the Memory.
    await startNewChat(page, log);
    await sendMessage(page, withMockMarker(SAVE_PROMPT, 'memory_reuse_save', 'fast'), log, screenshot, 'save-career-profile');
    await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
    if (MOCKED) await expect(page.getByTestId('mate-message-content').last()).toContainText('Saved your career profile.', { timeout: 60000 });
    const saveChatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(saveChatId).toBeTruthy();
    const notice = page.locator(NOTICE);
    await expect(notice).toHaveCount(1, { timeout: 90000 });
    await expect(notice.getByTestId('context-entry-event-label')).toHaveText(`The assistant saved a memory: ${TITLE}`);
    await testInfo.attach('save-notice-career-profile', { body: await page.screenshot(), contentType: 'image/png' });
    await screenshot(page, 'career-profile-saved');

    // Chat 2: the server asks to load the Memory, nothing is answered before approval.
    await startNewChat(page, log);
    await sendMessage(page, withMockMarker(LOAD_PROMPT, 'memory_reuse_load', 'fast'), log, screenshot, 'ask-about-employer');
    const dialog = page.getByTestId('app-settings-memories-permission-dialog');
    await expect(dialog).toBeVisible({ timeout: 90000 });
    await expect(dialog.getByText(TITLE, { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('mate-message-content')).toHaveCount(0);
    await testInfo.attach('permission-dialog-names-career-profile', {
      body: await dialog.screenshot(), contentType: 'image/png'
    });

    // Approve: the continuation answers with the Memory's content.
    await dialog.getByTestId('btn-include').click();
    await expect(dialog).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('mate-message-content').last()).toContainText('Example Retail GmbH', { timeout: 180000 });
    await expect(page.getByTestId('stop-processing-button')).not.toBeVisible({ timeout: 60000 });
    // The user message names what was shared in readable words, never a raw id.
    await expect(page.getByTestId('app-settings-memory-category-badge')).toHaveText('Memories (1)', { timeout: 20000 });
    await testInfo.attach('answer-uses-career-profile', {
      body: await page.screenshot(), contentType: 'image/png'
    });

    // Cleanup: Undo the save notice in chat 1 so reruns start clean.
    await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(saveChatId as string)}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', saveChatId as string, { timeout: 60000 });
    await expect(notice).toHaveCount(1, { timeout: 30000 });
    await notice.getByTestId('context-entry-event-undo').click();
    await expect(notice).toHaveAttribute('data-undone', 'true', { timeout: 20000 });
    await screenshot(page, 'career-profile-removed');
  });
});
