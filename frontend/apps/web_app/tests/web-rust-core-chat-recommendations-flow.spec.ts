/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)
/**
 * Chat Recommendations card (replaced quick tips), VITE_OPENMATES_RUST_CORE=1 build.
 *
 * With the chat sidebar closed: a conference planning reply shows the Recommendations
 * card between the history and the follow-up chips with at least one memory and never
 * a workflow (workflow suggestions are not shown in the open chat, like linked Tasks),
 * one dot per recommendation and working previous/next controls. A memory
 * recommendation opens an unsaved draft in Settings > Memories; only Save removes the
 * recommendation and adds the encrypted "Memory created: <title>" history event whose
 * link opens the memory. The state survives a reload. The workflow recommendations of
 * the chat are offered on the Workflows start screen, not in the chat. With the
 * setting off no card is shown.
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

function memoryDocument(title: string): string {
  return `---\ntitle: ${title}\nwhen_to_use: planning conference visits\nload_mode: ask_first\n---\n\nBalance talks, hallway conversations and rest breaks.\n`;
}

test.describe('chat recommendations', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
  test('card, memory save, history events, reload, dismiss and setting off', async ({ page }: { page: Page }) => {
    test.setTimeout(300000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.setViewportSize({ width: 1280, height: 900 });
    const log = createSignupLogger('CHAT_RECOMMENDATIONS');
    const screenshot = createStepScreenshotter(log);

    const createDraftBodies: Array<Record<string, unknown>> = [];
    let createDraftAttempts = 0;
    if (USE_MOCKS) {
      await page.route('**/v1/memory-suggestions/create-draft', async (route: Route) => {
        createDraftAttempts += 1;
        // First attempt: the connection fails before any response (Safari "Load failed"); the app retries once.
        if (createDraftAttempts === 1) {
          await route.abort('failed');
          return;
        }
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

    /** Pages forward until the visible recommendation has the kind. */
    // Shows the first "create" recommendation of a kind (Create opens a new draft;
    // Update opens the existing entry's preview instead).
    async function showKind(kind: 'memory'): Promise<string> {
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

      // Card: memory recommendations only (never a workflow), one dot each, previous/next work.
      await expect(card).toBeVisible({ timeout: 90000 });
      const total = Number(await card.getAttribute('data-count'));
      expect(total).toBeGreaterThanOrEqual(1);
      if (USE_MOCKS) expect(total).toBe(2);
      await expect(card).not.toContainText(/workflow recommended/i);
      await expect(page.getByTestId('recommendation-dot')).toHaveCount(total);
      await expect(card).toHaveAttribute('data-index', '0');
      const firstTitle = await page.getByTestId('recommendation-title').textContent();
      if (total > 1) {
        await page.getByTestId('recommendation-next').click();
        await expect(card).toHaveAttribute('data-index', '1');
        await expect(page.getByTestId('recommendation-dot').nth(1)).toHaveAttribute('aria-current', 'true');
        await expect(page.getByTestId('recommendation-title')).not.toHaveText(firstTitle ?? '');
        await page.getByTestId('recommendation-previous').click();
        await expect(card).toHaveAttribute('data-index', '0');
        await expect(page.getByTestId('recommendation-title')).toHaveText(firstTitle ?? '');
        await page.getByTestId('recommendation-previous').click();
        await expect(card).toHaveAttribute('data-index', String(total - 1));
      }
      await expect(page.getByTestId('recommendation-embed').first()).toBeVisible();
      await screenshot(page, 'recommendations-card');
      const kinds = new Set<string>();
      for (let index = 0; index < total; index += 1) {
        kinds.add((await item.getAttribute('data-kind')) ?? '');
        if (total > 1) await page.getByTestId('recommendation-next').click();
      }
      expect([...kinds]).toEqual(['memory']);

      // Memory: Create opens an unsaved draft; the recommendation stays until Save.
      const memoryTitle = await showKind('memory');
      await page.getByTestId('recommendation-action').click();
      await expect(page.getByTestId('memory-draft-banner')).toBeVisible({ timeout: 60000 });
      await expect(page.getByTestId('rule-title')).toHaveValue(memoryTitle);
      if (USE_MOCKS) {
        expect(createDraftAttempts).toBe(2);
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
      await expect(memoryNotice.getByTestId('context-entry-event-label')).toHaveText(memoryTitle);
      await expect(memoryNotice.getByTestId('context-entry-event-open')).toHaveAttribute('aria-label', `Memory created: ${memoryTitle}`);
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

      // Workflows start screen: the suggestions above the input are the workflow
      // recommendations of the user's chats, newest first, with no source label (Marco, 21 Nov).
      const chatUrl = page.url();
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      const workflowSuggestions = page.getByTestId('workflows-start-suggestions');
      const suggestedItem = workflowSuggestions.getByTestId('follow-up-suggestion-item').first();
      await expect(suggestedItem).toBeVisible({ timeout: 30000 });
      const composerBox = await page.getByTestId('workflow-input-composer').boundingBox();
      const suggestionsBox = await workflowSuggestions.boundingBox();
      expect(suggestionsBox!.y + suggestionsBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
      await test.info().attach('desktop-workflows-suggestions-from-chats', { body: await page.screenshot(), contentType: 'image/png' });
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(suggestedItem).toBeVisible();
      await test.info().attach('phone-workflows-suggestions-from-chats', { body: await page.screenshot(), contentType: 'image/png' });
      await page.setViewportSize({ width: 1280, height: 720 });
      await suggestedItem.click();
      await expect(page.getByTestId('workflow-input-textarea')).not.toHaveValue('');
      await screenshot(page, 'workflows-suggestion-from-chat-filled');
      await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60000 });
      await expect(card).toHaveAttribute('data-count', String(total - 1), { timeout: 60000 });

      // Workflow suggestions never appear in the open chat.
      await expect(page.locator('[data-testid="recommendation-item"][data-kind="workflow"]')).toHaveCount(0);

      // No dismiss control; saved entries stay removed and the rest remain after a reload.
      await expect(page.getByTestId('recommendation-dismiss')).toHaveCount(0);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60000 });
      await expect(notices).toHaveCount(1, { timeout: 60000 });
      if (total > 1) await expect(card).toHaveAttribute('data-count', String(total - 1), { timeout: 60000 });
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
