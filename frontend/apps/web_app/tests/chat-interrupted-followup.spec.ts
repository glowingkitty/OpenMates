/* eslint-disable @typescript-eslint/no-require-imports */
/** Real disposable backend cancellation and encrypted recovery; no provider calls. */
import type { AITypingStartedPayload } from "../../../packages/ui/src/types/chat";
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, waitForChatReady, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { waitForContextSyncComplete, openChatAfterContextSync } = require('./helpers/chat-hydration');
const { ensureIsolatedRecoveryEpoch } = require('./helpers/recovery-epoch');
const { email, password, otpKey } = getTestAccount();

test.describe('Interrupted personal chat follow-ups', () => {
  test.describe.configure({ timeout: 240_000 });
  skipWithoutCredentials(test, email, password, otpKey);
  test.beforeAll(() => ensureIsolatedRecoveryEpoch('chat-interrupted-followup.spec.ts'));
  for (const partial of [true, false]) {
    // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced,chats.completion.recovery-takeover,chat-processing-feedback.turn-lifecycle,chat-queued-followups.admission.synced
    test(`sends the waiting follow-up after Stop ${partial ? 'during streamed text' : 'before the first text'}`, async ({ page }: { page: any }, testInfo: any) => {
      const frames: Array<{ direction: string; type: string; payload: any }> = [];
      page.on('websocket', (socket: any) => {
        if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
        for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']]) {
          socket.on(event, (frame: any) => {
            try {
              const data = JSON.parse(String(frame.payload));
              frames.push({ direction, type: data.type, payload: data.payload });
            } catch { /* Ignore control frames. */ }
          });
        }
      });
      let chatId: string | null = null;
      try {
        await loginToTestAccount(page);
        await waitForChatReady(page);
        await waitForContextSyncComplete(page, testInfo);
        await sendMessage(page, withMockMarker('Start a long explanation for interruption verification.', 'chat_interrupt_followup', 'instant'));
        const admission = frames.find(f => f.direction === 'sent' && ['chat_message_added', 'chat_turn_admit'].includes(f.type));
        expect(admission?.payload.protocol_version).toBe(1);
        expect(typeof admission?.payload.turn_id).toBe('string');
        chatId = admission!.payload.chat_id;
        const started = (): AITypingStartedPayload | undefined => frames.find(f => f.direction === 'received'
          && f.type === 'ai_typing_started' && f.payload?.chat_id === chatId)?.payload;
        await expect.poll(started, { timeout: 60_000 }).toBeTruthy();
        const taskId = started()!.message_id;
        expect(typeof taskId).toBe('string');
        expect(taskId.length).toBeGreaterThan(0);
        const stop = page.getByTestId('stop-processing-button');
        await expect(stop).toBeVisible();
        if (partial) {
          await expect(page.getByTestId('message-assistant')).toContainText('This partial response must survive interruption.', { timeout: 60_000 });
        }
        await sendMessage(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'instant'), undefined, undefined, 'follow-up', { waitUntil: 'visible' });
        await expect(page.getByTestId('message-user')).toHaveCount(2);
        const followup = page.getByTestId('message-user').last();
        const followupId = await followup.getAttribute('data-message-id');
        expect(followupId).toBeTruthy();
        // A follow-up during a running reply goes to the server at once and
        // waits there as Queued (feature.chat-queued-followups admission.synced).
        await expect.poll(() => frames.filter(f => f.direction === 'sent' && ['chat_message_added', 'chat_turn_admit'].includes(f.type)
          && (f.payload?.message?.message_id ?? f.payload?.message_id) === followupId).length, { timeout: 10_000 }).toBe(1);
        await expect(followup.getByTestId('queued-followup-status')).toHaveText('Queued', { timeout: 10_000 });
        if (!partial) expect(frames.some(f => f.direction === 'received' && f.payload?.task_id === taskId
          && typeof f.payload?.full_content_so_far === 'string' && f.payload.full_content_so_far.length > 0)).toBe(false);
        await stop.click();
        await expect.poll(() => frames.some(f => f.direction === 'received'
          && f.type === 'recovery_job_persisted' && f.payload?.state === 'TERMINAL'), { timeout: 60_000 }).toBe(true);
        await waitForAssistantMessage(page, { contains: 'Berlin', timeout: 90_000 });
        await expect.poll(() => frames.filter(f => f.direction === 'received'
          && f.type === 'recovery_job_persisted' && f.payload?.state === 'TERMINAL').length, { timeout: 60_000 }).toBe(2);
        expect(frames.filter(f => f.direction === 'sent' && ['chat_message_added', 'chat_turn_admit'].includes(f.type)
          && (f.payload?.message?.message_id ?? f.payload?.message_id) === followupId)).toHaveLength(1);
        expect(frames.filter(f => f.direction === 'sent' && f.type === 'ai_response_completed'
          && f.payload?.message?.message_id === taskId)).toHaveLength(0);
        expect(frames.some(f => f.direction === 'received' && f.payload?.code === 'recovery_persistence_required')).toBe(false);
        expect(frames.filter(f => f.direction === 'received' && f.type === 'ai_task_failed'
          && (f.payload?.task_id === taskId || f.payload?.chat_id === chatId))).toHaveLength(0);
        if (partial) await expect(page.getByTestId('message-assistant').first()).toContainText('This partial response must survive interruption.');
        // Cold client storage must reconstruct both accepted user turns and the
        // follow-up answer from encrypted canonical history, without duplicates.
        await page.evaluate(async () => {
          const db = await new Promise<IDBDatabase>((resolve, reject) => {
            const req = indexedDB.open('chats_db'); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
          });
          const stores = ['chats', 'messages', 'embeds', 'embed_keys'].filter(name => db.objectStoreNames.contains(name));
          await new Promise<void>((resolve, reject) => {
            const transaction = db.transaction(stores, 'readwrite');
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
            for (const name of stores) transaction.objectStore(name).clear();
          });
          db.close();
          localStorage.clear();
        });
        await page.reload({ waitUntil: 'domcontentloaded' });
        await waitForChatReady(page);
        await openChatAfterContextSync(page, chatId, testInfo);
        await expect(page.getByTestId('message-user')).toHaveCount(2);
        await expect(page.getByTestId('message-assistant').last()).toContainText('Berlin');
        if (partial) await expect(page.getByTestId('message-assistant').first()).toContainText('This partial response must survive interruption.');
      } catch (error) {
        await testInfo.attach('interruption-state', { body: await page.screenshot(), contentType: 'image/png' });
        throw error;
      } finally {
        // Keep safe protocol codes for failures, never message bodies or ciphertext.
        await testInfo.attach('interruption-events', { body: JSON.stringify(frames.map(f => ({ direction: f.direction, type: f.type,
          ...(f.type === 'error' && typeof f.payload?.code === 'string' ? { code: f.payload.code } : {}),
        }))), contentType: 'application/json' });
        if (chatId) await deleteActiveChat(page).catch(() => {});
      }
    });
  }
});
