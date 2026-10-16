/* eslint-disable @typescript-eslint/no-require-imports */
/** Queue UI contract through authenticated chat, local encrypted storage and WS handlers. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { openChatAfterContextSync, clickReadyComposerSend } = require('./helpers/chat-hydration');

const { email, password, otpKey } = getTestAccount();

async function installQueueSocketFixture(context: any, chatId: string): Promise<void> {
  await context.addInitScript(({ fixtureChatId }: { fixtureChatId: string }) => {
    const NativeWebSocket = window.WebSocket;
    let activeSocket: WebSocket | null = null;
    const frames: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const emit = (type: string, payload: Record<string, unknown>) => {
      if (!activeSocket) throw new Error('Queue fixture WebSocket is unavailable');
      activeSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, payload }) }));
    };
    function FixtureWebSocket(this: WebSocket, ...args: ConstructorParameters<typeof WebSocket>) {
      const socket = new NativeWebSocket(...args);
      activeSocket = socket;
      const nativeSend = socket.send.bind(socket);
      socket.send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
        if (typeof data === 'string') {
          try {
            const frame = JSON.parse(data);
            if (frame?.payload?.chat_id === fixtureChatId && frame.type === 'revise_queued_message') {
              frames.push({ type: frame.type, payload: frame.payload });
              const payload = frame.payload as Record<string, unknown>;
              setTimeout(() => emit('queued_message_updated', {
                chat_id: fixtureChatId,
                message_id: payload.message_id,
                client_request_id: payload.client_request_id,
                queue_mode: payload.queue_mode ?? 'follow_up',
                queue_revision: Number(payload.expected_revision) + 1,
                ...(payload.encrypted_content ? { encrypted_content: payload.encrypted_content } : {}),
                ...(payload.encrypted_pii_mappings !== undefined ? { encrypted_pii_mappings: payload.encrypted_pii_mappings } : {}),
              }), 0);
              return;
            }
            if (frame?.payload?.chat_id === fixtureChatId && frame.type === 'chat_message_added') {
              frames.push({ type: frame.type, payload: frame.payload });
              return;
            }
            if (frame?.payload?.chat_id === fixtureChatId) return;
          } catch { /* Keep ordinary WebSocket traffic. */ }
        }
        nativeSend(data);
      };
      return socket;
    }
    Object.setPrototypeOf(FixtureWebSocket, NativeWebSocket);
    FixtureWebSocket.prototype = NativeWebSocket.prototype;
    Object.defineProperty(window, 'WebSocket', { configurable: true, writable: true, value: FixtureWebSocket });
    (window as typeof window & { __queuedFollowupFixture?: unknown }).__queuedFollowupFixture = { frames, emit };
  }, { fixtureChatId: chatId });
}

async function seedQueueChat(
  page: any,
  chatId: string,
  queuedMessageId: string,
  queuedState: { content: string; revision: number; mode: 'follow_up' | 'steer' } = {
    content: 'Original follow up', revision: 1, mode: 'follow_up',
  },
): Promise<void> {
  await page.evaluate(async ({ chatId, queuedMessageId, queuedState }: {
    chatId: string;
    queuedMessageId: string;
    queuedState: { content: string; revision: number; mode: 'follow_up' | 'steer' };
  }) => {
    const seed = (window as typeof window & { __openmatesE2ESeedChat?: (value: unknown) => Promise<unknown> }).__openmatesE2ESeedChat;
    if (!seed) throw new Error('E2E chat seed helper is unavailable');
    const now = Math.floor(Date.now() / 1000);
    await seed({
      chat: { chat_id: chatId, title: 'Queued follow-up fixture', messages_v: 2, title_v: 1,
        created_at: now, updated_at: now, last_edited_overall_timestamp: now },
      messages: [
        { message_id: `${chatId}-first`, chat_id: chatId, role: 'user', created_at: now - 1,
          status: 'synced', content: 'First question while the assistant works.' },
        { message_id: queuedMessageId, chat_id: chatId, role: 'user', created_at: now,
          status: 'queued', queue_revision: queuedState.revision, queue_mode: queuedState.mode,
          content: queuedState.content },
      ],
    });
  }, { chatId, queuedMessageId, queuedState });
}

test.describe('Queued follow-ups in authenticated chat', () => {
  test.describe.configure({ timeout: 180000 });
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.cancel,chat-queued-followups.editing.stable-revision,chat-queued-followups.steering.safe-boundary
  test('keeps one queued row through cancel, unchanged Send, changed Send, and steer fallback', async ({ page }: { page: any }) => {
    const chatId = `e2e-queued-followup-${Date.now()}`;
    const messageId = `${chatId}-follow-up`;
    await installQueueSocketFixture(page.context(), chatId);
    await loginToTestAccount(page);
    // The fixture is local-only; seed after the account's initial remote sync
    // so an older in-flight snapshot cannot replace the selected chat.
    await expect.poll(() => page.evaluate(async () =>
      (await (window as any).__openmatesE2EChatConnectionState?.())?.contextSyncCompleted === true),
    { timeout: 45_000 }).toBe(true);
    await seedQueueChat(page, chatId, messageId);
    await openChatAfterContextSync(page, chatId, test.info());

    const row = page.locator(`[data-message-id="${messageId}"]`);
    const activeChat = page.getByTestId('active-chat-container');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await expect(activeChat).toHaveAttribute('data-current-chat-id', chatId);
    await expect(row.getByTestId('queued-followup-status')).toHaveText('Queued');
    await editor.fill('An independent unsent draft');
    await row.getByTestId('queued-followup-edit').click();
    await expect(page.getByTestId('queued-edit-banner')).toContainText('Editing queued message');
    await expect(editor).toContainText('Original follow up');
    await page.getByTestId('queued-edit-cancel').click();
    await expect(editor).toContainText('An independent unsent draft');
    await expect(page.getByTestId('queued-edit-banner')).toHaveCount(0);
    await expect(activeChat).toHaveAttribute('data-current-chat-id', chatId);

    await row.getByTestId('queued-followup-edit').click();
    await expect(page.getByTestId('queued-edit-banner')).toBeVisible();
    await expect(editor).toContainText('Original follow up');
    // A compact composer must send the unchanged queued edit on its first click.
    await row.getByTestId('queued-followup-status').click();
    await expect(page.getByTestId('message-field')).toHaveAttribute('data-focused', 'false');
    const compactSend = page.getByTestId('composer-send-button').filter({ visible: true });
    await expect(compactSend).toHaveCount(1);
    await expect(compactSend).toHaveAttribute('aria-label', 'Send');
    await expect(compactSend.locator('svg[aria-hidden="true"]')).toBeVisible();
    await clickReadyComposerSend(page);
    await expect(page.getByTestId('queued-edit-banner')).toHaveCount(0);
    expect(await page.evaluate(() => ((window as any).__queuedFollowupFixture.frames as unknown[]).length)).toBe(0);
    await expect(editor).toContainText('An independent unsent draft');

    await row.getByTestId('queued-followup-edit').click();
    await expect(page.getByTestId('queued-edit-banner')).toBeVisible();
    await expect(editor).toContainText('Original follow up');
    await editor.fill('Edited follow up with more detail');
    await expect(editor).toHaveText('Edited follow up with more detail');
    await clickReadyComposerSend(page);
    await expect.poll(() => page.evaluate(() => (window as any).__queuedFollowupFixture.frames.length)).toBe(1);
    expect(await page.evaluate(() => (window as any).__queuedFollowupFixture.frames.map((frame: { type: string }) => frame.type)))
      .toEqual(['revise_queued_message']);
    await expect(row).toContainText('Edited follow up with more detail');
    await expect(page.getByTestId('queued-edit-banner')).toHaveCount(0);
    await expect(editor).toContainText('An independent unsent draft');
    const editFrame = await page.evaluate(() => (window as any).__queuedFollowupFixture.frames[0]);
    expect(editFrame.payload.message_id).toBe(messageId);
    expect(editFrame.payload.expected_revision).toBe(1);
    expect(editFrame.payload.content).toBe('Edited follow up with more detail');
    expect(editFrame.payload.encrypted_content).toBeTruthy();
    await expect(page.locator(`[data-message-id="${messageId}"]`)).toHaveCount(1);

    await row.getByTestId('queued-followup-steer').click();
    await expect.poll(() => page.evaluate(() => (window as any).__queuedFollowupFixture.frames.length)).toBe(2);
    await expect(row.getByTestId('queued-followup-status')).toHaveText('Steering current response');
    const steerFrame = await page.evaluate(() => (window as any).__queuedFollowupFixture.frames[1]);
    expect(steerFrame.payload.message_id).toBe(messageId);
    expect(steerFrame.payload.expected_revision).toBe(2);
    expect(steerFrame.payload.queue_mode).toBe('steer');
    expect(steerFrame.payload.encrypted_content).toBeUndefined();

    const deferredQueueRevision = 4;
    await page.evaluate(({ chatId, messageId, deferredQueueRevision }: {
      chatId: string; messageId: string; deferredQueueRevision: number;
    }) => {
      (window as any).__queuedFollowupFixture.emit('queued_message_steer_deferred', {
        chat_id: chatId, message_id: messageId, queue_mode: 'follow_up',
        queue_revision: deferredQueueRevision, reason_code: 'unsafe_boundary',
      });
    }, { chatId, messageId, deferredQueueRevision });
    await expect(row.getByTestId('queued-followup-status')).toHaveText('Queued');
    await expect(row.getByTestId('queued-followup-error')).toContainText('remains queued');
    const queuedContent = row.getByTestId('message-content');
    await expect(queuedContent).toHaveText('Edited follow up with more detail');
    const peerQueuedState = {
      content: await queuedContent.innerText(),
      revision: deferredQueueRevision,
      mode: 'follow_up' as const,
    };
    expect(peerQueuedState.content).toBe('Edited follow up with more detail');
    await expect(row).toHaveCount(1);

    // This is a local UI fixture: the peer's initial server sync can remove a
    // chat seeded only in IndexedDB. Seed the verified final state after sync,
    // then test peer hydration. Distinct-connection broadcast/revision behavior
    // is covered by chat-queued-followups-protocol.spec.ts.
    const otherTab = await page.context().newPage();
    try {
      await otherTab.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      await waitForChatReady(otherTab);
      await expect.poll(() => otherTab.evaluate(async () =>
        (await (window as any).__openmatesE2EChatConnectionState?.())?.contextSyncCompleted === true),
      { timeout: 45_000 }).toBe(true);
      await seedQueueChat(otherTab, chatId, messageId, peerQueuedState);
      await openChatAfterContextSync(otherTab, chatId, test.info());
      const otherRow = otherTab.locator(`[data-message-id="${messageId}"]`);
      await expect(otherRow).toContainText('Edited follow up with more detail');
      await expect(otherRow.getByTestId('queued-followup-status')).toHaveText('Queued');

      // A newer revision from that tab leaves this tab's open edit intact and visibly stale.
      await row.getByTestId('queued-followup-edit').click();
      await editor.fill('Local revision that must remain in the composer');
      await page.evaluate(({ chatId, messageId }: { chatId: string; messageId: string }) => {
        (window as any).__queuedFollowupFixture.emit('queued_message_updated', {
          chat_id: chatId, message_id: messageId, queue_mode: 'follow_up', queue_revision: 5,
        });
      }, { chatId, messageId });
      await expect(page.getByTestId('queued-edit-error')).toContainText('another device');
      await expect(editor).toContainText('Local revision that must remain in the composer');
      await page.getByTestId('queued-edit-cancel').click();
      await expect(editor).toContainText('An independent unsent draft');
      await expect(page.locator(`[data-message-id="${messageId}"]`)).toHaveCount(1);
    } finally {
      await otherTab.close();
    }
  });
});
