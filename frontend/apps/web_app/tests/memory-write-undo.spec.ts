/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)
/**
 * Assistant Memory write with Undo, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * The user asks the assistant to remember a fact. The web client (memory_write_jobs
 * capability, Rust core job runner) saves it with no review step and the chat shows
 * "The assistant saved a memory: <title>" with Open and Undo. The Memory is listed in
 * Settings > Memories. Undo deletes it, the notice reads "Undone", the Memory is gone
 * from Settings, and a reload keeps the undone state (persisted undone marker).
 *
 * Mock mode (E2E_USE_MOCKS): the memory_write_undo fixture declares the save_memory
 * call, which mock replay dispatches through the real job protocol.
 * Plan: docs/plans/assistant-memory-writes/plan.yml (TASK-3).
 */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
  loginToTestAccount, sendMessage, setChatSidebarOpen, startNewChat, waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const {
  createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, withMockMarker
} = require('./signup-flow-helpers');

const PROMPT = 'Please save this as a memory: my favourite test colour is teal.';
const TITLE = 'Favourite test colour';

/** Opens Settings > Memories and returns the private Memory rows matching TITLE. */
async function openMemories(page: Page) {
  await page.getByTestId('profile-container').click();
  const menu = page.locator('[data-testid="settings-menu"].visible');
  await expect(menu).toBeVisible({ timeout: 10000 });
  await menu.getByRole('menuitem', { name: /^Memories$/i }).first().click();
  const editor = page.locator('[data-testid="memories-editor"][data-source="personal"]');
  await expect(editor).toBeVisible({ timeout: 20000 });
  return editor.getByTestId('memory-row').filter({ hasText: TITLE });
}

test.describe('assistant memory writes', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
  test('assistant saves a memory without review, Undo removes it and survives a reload', async ({ page }: { page: Page }) => {
    test.setTimeout(240000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    const log = createSignupLogger('MEMORY_WRITE_UNDO');
    const screenshot = createStepScreenshotter(log);

    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, screenshot);
    await setChatSidebarOpen(page, false, log);

    await startNewChat(page, log);
    await sendMessage(page, withMockMarker(PROMPT, 'memory_write_undo', 'fast'), log, screenshot, 'remember');
    await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
    const chatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(chatId).toBeTruthy();

    // The notice appears with no review step (no draft banner, no Save).
    const notice = page.locator('[data-testid="context-entry-event"][data-kind="memory"][data-source="assistant"]');
    await expect(notice).toHaveCount(1, { timeout: 60000 });
    await expect(notice.getByTestId('context-entry-event-label')).toHaveText(`The assistant saved a memory: ${TITLE}`);
    await expect(page.getByTestId('memory-draft-banner')).toHaveCount(0);
    await expect(notice.getByTestId('context-entry-event-undo')).toBeEnabled();
    await screenshot(page, 'assistant-memory-notice');

    // The Memory is saved in Settings > Memories.
    await notice.getByTestId('context-entry-event-open').click();
    await expect(page.getByTestId('rule-title')).toHaveValue(TITLE, { timeout: 20000 });
    await page.getByTestId('icon-button-close').click();
    await expect(await openMemories(page)).toHaveCount(1, { timeout: 20000 });
    await screenshot(page, 'memory-in-settings');
    await page.getByTestId('icon-button-close').click();

    // Undo deletes it and marks the notice undone.
    await notice.getByTestId('context-entry-event-undo').click();
    await expect(notice).toHaveAttribute('data-undone', 'true', { timeout: 20000 });
    await expect(notice.getByTestId('context-entry-event-undone')).toHaveText('Undone');
    await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
    await expect(notice.getByTestId('context-entry-event-undo-error')).toHaveCount(0);
    await screenshot(page, 'memory-undone');
    await expect(await openMemories(page)).toHaveCount(0, { timeout: 20000 });
    await screenshot(page, 'memory-gone-from-settings');
    await page.getByTestId('icon-button-close').click();

    // A reload keeps the undone state.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId as string, { timeout: 60000 });
    await expect(notice).toHaveCount(1, { timeout: 30000 });
    await expect(notice).toHaveAttribute('data-undone', 'true', { timeout: 30000 });
    await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
    await screenshot(page, 'undone-after-reload');
  });
});
