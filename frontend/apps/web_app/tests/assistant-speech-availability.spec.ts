/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// Core account plus fictional local chat; no inference or provider request.
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { createSignupLogger, getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: supporting surface=gui.web assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.failure.nonblocking-visible-resumable
test('private Speak follows provider availability and surfaces rejected work', async ({ page }: { page: any }) => {
  test.setTimeout(180_000);
  const chatId = 'd9b1d479-a92d-427d-bc56-b218d9e40f38';
  let available = true;
  let speechRequests = 0;
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route(/\/v1\/apps\/metadata(?:\?.*)?$/, (route: any) => route.fulfill({
    json: { assistant_speech_available: available, apps: { audio: { id: 'audio', skills: [] } } },
  }));
  page.on('websocket', (socket: any) => socket.on('framesent', (event: any) => {
    try {
      const frame = JSON.parse(String(event.payload));
      if (frame.type === 'assistant_speech' && frame.payload?.action === 'request') speechRequests += 1;
    } catch { /* Ignore transport frames. */ }
  }));
  await loginToTestAccount(page, createSignupLogger('assistant-speech-availability'));
  await page.evaluate(async (id: string) => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('chats_db');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(['chats', 'messages'], 'readwrite');
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => reject(tx.error);
      const now = Math.floor(Date.now() / 1000);
      tx.objectStore('chats').put({
        chat_id: id, title: 'Speech availability fixture', encrypted_title: null,
        messages_v: 1, title_v: 1, metadata_v: 1, draft_v: 0,
        created_at: now, updated_at: now, last_edited_overall_timestamp: now,
        unread_count: 0, is_shared: false, is_incognito: false,
      });
      tx.objectStore('messages').put({
        message_id: '1a11cbb0-a9f2-4e52-9ba9-f8869185fa6b', chat_id: id,
        role: 'assistant', content: 'This fictional response can be read without speech.',
        encrypted_content: null, status: 'synced', created_at: now,
      });
    });
  }, chatId);
  await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
  const message = page.getByTestId('message-assistant').filter({ hasText: 'This fictional response' });
  const speak = message.getByTestId('assistant-message-speak');
  await expect(speak).toBeVisible({ timeout: 30_000 });
  await speak.click();
  // The local fixture has no server-owned chat. Authorization must reject it
  // before any provider dispatch, and the actual player must leave Loading.
  const player = page.getByTestId('assistant-speech-player');
  await expect(player).toHaveAttribute('data-status', 'failed', { timeout: 15_000 });
  await expect(player.getByTestId('assistant-speech-error')).toBeVisible();
  await expect(player.getByTestId('assistant-speech-loading')).toHaveCount(0);
  await player.getByTestId('assistant-speech-close').click();
  expect(speechRequests).toBe(1);

  available = false;
  await page.reload();
  await expect(message).toBeVisible({ timeout: 30_000 });
  await expect(speak).toHaveCount(0);
  expect(speechRequests).toBe(1);
  available = true;
  await page.reload();
  await expect(speak).toBeVisible({ timeout: 30_000 });
});
