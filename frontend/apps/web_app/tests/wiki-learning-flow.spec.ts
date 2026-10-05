import { expect, test } from './helpers/cookie-audit';
import { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat, waitForChatReady, fillMessageEditor } from './helpers/chat-test-helpers';
import { dismissComposerFocus } from './helpers/composer-focus';
import { returnToChatWorkspace } from './helpers/workspace-navigation';
import { withMockMarker, installE2EServerContentOverrideGate } from './signup-flow-helpers';

// Synthetic replay covers real encryption, WebSocket submission, persistence and memory sync.
// The public question mock carries the replay marker; no provider inference runs in CI.
const title = 'Ada Lovelace';
const sourceUrl = 'https://en.wikipedia.org/wiki/Ada_Lovelace';
const question = 'How did Ada Lovelace contribute to computing?';
const draft = 'My unfinished comparison of Ada Lovelace and Charles Babbage.';
const captured = new WeakMap<object, {
  entries: Record<string, unknown>[];
  submissions: { chatId: string; preserveDraft: boolean }[];
  draftEvents: Record<string, unknown>[];
}>();
const summaries: Record<string, Record<string, string>> = {
  'Ada Lovelace': { title, extract: 'Ada Lovelace explored symbolic computation.', description: 'English mathematician' },
  'Charles Babbage': { title: 'Charles Babbage', extract: 'Charles Babbage designed the analytical engine.', description: 'Mathematician and inventor' },
};

async function recordDraftCheckpoint(page: import('@playwright/test').Page, stage: string): Promise<void> {
  const state = await page.evaluate(expectedDraft => {
    const hook = (window as unknown as { __openmatesE2EDraftState?: () => Record<string, unknown> }).__openmatesE2EDraftState;
    const state = hook?.();
    const input = document.querySelector('[data-action="message-input"]');
    const editor = Array.from(document.querySelectorAll('[data-testid="message-editor"]')).at(-1);
    return {
      inputChatId: input?.getAttribute('data-current-chat-id'),
      currentChatId: state?.currentChatId,
      version: state?.currentUserDraftVersion,
      hasUnsavedChanges: state?.hasUnsavedChanges,
      isSaveInProgress: state?.isSaveInProgress,
      isSwitchingContext: state?.isSwitchingContext,
      savedTextMatches: state?.lastSavedContentMarkdown === expectedDraft,
      savedTextLength: typeof state?.lastSavedContentMarkdown === 'string' ? state.lastSavedContentMarkdown.length : null,
      visibleTextMatches: editor?.textContent === expectedDraft,
      restoreEvents: (window as unknown as { __openmatesMessageInputDraftDiagnostics?: Record<string, unknown>[] }).__openmatesMessageInputDraftDiagnostics,
    };
  }, draft);
  console.info('Wiki draft checkpoint', JSON.stringify({ stage, state, events: captured.get(page)!.draftEvents }));
}

test.beforeEach(async ({ page }, testInfo) => {
  test.setTimeout(180000);
  await installE2EServerContentOverrideGate(page, 'wiki-learning-flow');
  if (testInfo.title.includes('local admission rejects')) {
    await page.route('**/v1/settings/server-status', async route => {
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({ json: { ...data, is_self_hosted: true, ai_models_configured: false } });
    });
  }
  const frames = { entries: [] as Record<string, unknown>[], submissions: [] as { chatId: string; preserveDraft: boolean }[], draftEvents: [] as Record<string, unknown>[] };
  captured.set(page, frames);
  page.on('websocket', socket => {
    for (const direction of ['framesent', 'framereceived'] as const) socket.on(direction, frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        if (['update_draft', 'delete_draft', 'chat_draft_updated', 'chat_draft_deleted'].includes(message.type)) {
          frames.draftEvents.push({ direction, type: message.type, chatId: message.payload?.chat_id,
            version: message.payload?.draft_v ?? message.payload?.versions?.draft_v,
            hasEncryptedDraft: !!(message.payload?.encrypted_draft_md ?? message.payload?.data?.encrypted_draft_md) });
        }
      } catch { /* Non-JSON frames contain no relevant draft metadata. */ }
    });
    socket.on('framesent', frame => {
    try {
      const message = JSON.parse(String(frame.payload));
      if (message.type === 'store_app_settings_memories_entry') frames.entries.push(message.payload.entry);
      if (message.type === 'chat_message_added') frames.submissions.push({ chatId: message.payload.chat_id, preserveDraft: message.payload.preserve_draft === true });
    } catch { /* Other transports are outside this assertion. */ }
    });
  });
  await page.route('**/v1/wikipedia/summary?**', route => {
    const requested = new URL(route.request().url()).searchParams.get('title')!.replaceAll('_', ' ');
    return route.fulfill({ json: summaries[requested] });
  });
  await page.route('**/v1/wikipedia/learning?**', route => {
    const url = new URL(route.request().url());
    const canonical = url.searchParams.get('title')!.replaceAll('_', ' ');
    return route.fulfill({ json: {
      canonical_title: canonical, language: url.searchParams.get('language'), source_url: sourceUrl,
      expires_in_seconds: 86400,
      questions: [withMockMarker(question, 'wiki_learning_flow')],
      related_articles: canonical === title ? [{ title: 'Charles Babbage', canonical_title: 'Charles Babbage', language: 'en', description: 'Mathematician and inventor' }] : [],
    } });
  });
  await loginToTestAccount(page);
  await waitForChatReady(page);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory,wikipedia-mentions.surfaces.semantic-parity
test('wiki actions save one encrypted Study interest and submit in the same chat while retaining its draft', async ({ page }) => {
  const { entries: storedEntries, submissions } = captured.get(page)!;
  await startNewChat(page);
  await sendMessage(page, withMockMarker('Help me explore Ada Lovelace.', 'wiki_learning_flow'), message => console.info(message));
  await expect(page.getByTestId('message-assistant').last()).toContainText('symbolic computation');
  const originalUrl = page.url();
  const originalChatId = originalUrl.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
  expect(originalChatId).toBeTruthy();
  const editor = page.getByTestId('message-editor').last();
  await fillMessageEditor(page, editor, draft);
  await dismissComposerFocus(page);
  await expect(editor).toContainText(draft);
  await recordDraftCheckpoint(page, 'typed-and-dismissed');
  await page.getByTestId('message-assistant').last().getByRole('link', { name: title, exact: true }).click();
  await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText(title);
  await expect(page.getByTestId('wiki-learning')).toContainText('in this chat');
  await page.getByTestId('wiki-save-interest').click();
  await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
  await page.getByTestId('wiki-related-article').click();
  await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText('Charles Babbage');
  await page.getByTestId('embed-minimize').click();
  await page.getByTestId('message-assistant').last().getByRole('link', { name: title, exact: true }).click();
  await expect(page.getByTestId('wiki-interest-saved')).toBeVisible();
  await expect(page.getByTestId('wiki-save-interest')).toHaveCount(0);
  await recordDraftCheckpoint(page, 'related-article-round-trip');
  await page.getByRole('button', { name: 'Edit learning goal', exact: true }).click();
  await expect(page.locator('#topic')).toHaveValue(title);
  await recordDraftCheckpoint(page, 'study-editor-open');
  await expect(page.locator('#difficulty_level')).toHaveValue('');
  await page.locator('.entry-detail').getByRole('button', { name: /cancel/i }).click();
  page.once('dialog', dialog => dialog.accept());
  await page.locator('.entry-detail').getByRole('button', { name: 'Delete', exact: true }).click();
  await recordDraftCheckpoint(page, 'study-editor-cleanup');
  await returnToChatWorkspace(page, originalUrl);
  await recordDraftCheckpoint(page, 'chat-reopened');
  await expect(page.getByTestId('message-editor').last()).toContainText(draft);
  await page.getByTestId('message-assistant').last().getByRole('link', { name: title, exact: true }).click();
  const userCount = await page.getByTestId('message-user').count();
  await page.getByTestId('wiki-question').first().click();
  await expect(page.getByTestId('wiki-fullscreen-content')).toHaveCount(0);
  await expect(page).toHaveURL(originalUrl);
  await expect(page.getByTestId('message-user')).toHaveCount(userCount + 1);
  await expect(page.getByTestId('message-user').last()).toContainText(question);
  await expect(page.getByTestId('message-editor').last()).toContainText(draft);
  await expect(page.getByTestId('message-assistant')).toHaveCount(2);
  await expect(page.getByTestId('message-assistant').last()).toContainText('symbolic computation');
  await page.reload();
  await expect(page.getByTestId('message-editor').last()).toContainText(draft, { timeout: 30000 });
  expect(storedEntries).toHaveLength(1);
  expect(storedEntries[0].encrypted_item_json).toBeTruthy();
  expect(JSON.stringify(storedEntries[0])).not.toContain(title);
  expect(submissions.at(-1)).toEqual({ chatId: originalChatId, preserveDraft: true });
  await deleteActiveChat(page);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
test('an article opened without chat context starts a new chat after its question is accepted', async ({ page }) => {
  await startNewChat(page);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('wikifullscreen', {
    detail: { wikiTitle: 'Ada_Lovelace', displayText: 'Ada Lovelace', language: 'en', hasChatContext: false },
  })));
  await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText(title);
  await expect(page.getByTestId('wiki-learning')).toContainText('start a new learning chat');
  await page.getByTestId('wiki-question').first().click();
  await expect(page.getByTestId('wiki-fullscreen-content')).toHaveCount(0);
  await expect(page).toHaveURL(/chat-id=/);
  await expect(page.getByTestId('message-user').last()).toContainText(question);
  await expect(page.getByTestId('message-assistant').last()).toContainText('symbolic computation');
  await deleteActiveChat(page);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
test('the article and draft remain when local admission rejects a question', async ({ page }) => {
  await startNewChat(page);
  const editor = page.getByTestId('message-editor').last();
  await fillMessageEditor(page, editor, draft);
  await expect(editor).toContainText(draft);
  await expect(page).toHaveURL(/chat-id=/);
  const originalUrl = page.url();
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('wikifullscreen', {
    detail: { wikiTitle: 'Ada_Lovelace', displayText: 'Ada Lovelace', language: 'en', hasChatContext: false },
  })));
  await expect(page.getByTestId('wiki-fullscreen-title')).toHaveText(title);
  await page.getByTestId('wiki-question').first().click();
  await expect(page.getByTestId('wiki-learning').getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('wiki-fullscreen-content')).toBeVisible();
  await expect(page.getByTestId('wiki-question').first()).toBeEnabled();
  await expect(page).toHaveURL(originalUrl);
  await page.getByTestId('embed-minimize').click();
  await expect(page.getByTestId('message-editor').last()).toContainText(draft);
});
