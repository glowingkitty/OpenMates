/**
 * Real first-party call transport and encrypted chat persistence in isolated CI.
 * Only the external voice provider is synthetic, gated inside the disposable
 * backend; browser sockets, session admission and message storage stay real.
 */
import type { Page } from '@playwright/test';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const USER_SPEECH = 'How do I make ramen?';
const ASSISTANT_SPEECH = 'For ramen, simmer the broth and cook the noodles.';
const PASTED_TEXT = 'Please use this pasted recipe: noodles, broth, mushrooms and ginger.';

interface SocketObservation {
  path: string;
  type: string;
  messageId?: string;
  chatId?: string;
  role?: string;
  ciphertextLength?: number;
  plaintext?: boolean;
  revision?: number;
  context?: Array<{ role: string; text: string }>;
}
interface CallEvidence {
  sent: SocketObservation[];
  received: SocketObservation[];
  tracks: MediaStreamTrack[];
  mainSocket?: WebSocket;
  reconnectOnText?: boolean;
  reconnectInjected?: boolean;
  heldChatLookupCount?: number;
  releaseChatLookup?: () => void;
}

test.use({
  actionTimeout: 30_000,
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

async function observeRealTransport(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const evidence = { sent: [], received: [], tracks: [] } as CallEvidence;
    Object.assign(window, { __voiceCallEvidence: evidence });
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct(Target, args) {
        const socket: WebSocket = Reflect.construct(Target, args);
        const path = new URL(String(args[0]), window.location.href).pathname;
        if (path !== '/v1/voice-call') evidence.mainSocket = socket;
        const originalSend = socket.send.bind(socket);
        socket.send = (data) => {
          if (typeof data === 'string') {
            try {
              const event = JSON.parse(data);
              const payload = event.payload ?? event;
              if (['start', 'text_input', 'call_message_completed', 'chat_message_added', 'mic_audio', 'hangup'].includes(event.type)) {
                evidence.sent.push({
                  path, type: event.type,
                  messageId: payload.message_id ?? payload.message?.message_id,
                  chatId: payload.chat_id, role: payload.role,
                  ...(event.type === 'call_message_completed' ? {
                    ciphertextLength: typeof payload.encrypted_content === 'string' ? payload.encrypted_content.length : 0,
                    plaintext: 'content' in payload || 'text' in payload,
                    revision: payload.revision,
                  } : {}),
                  ...(event.type === 'start' ? { context: payload.context?.messages } : {}),
                });
              }
            } catch { /* Observe without changing transport behavior. */ }
          }
          originalSend(data);
          if (path === '/v1/voice-call' && evidence.reconnectOnText && typeof data === 'string') {
            try {
              if (JSON.parse(data).type === 'text_input') {
                evidence.reconnectOnText = false;
                evidence.reconnectInjected = true;
                evidence.mainSocket?.close();
              }
            } catch { /* Preserve native transport if an unrelated frame arrives. */ }
          }
        };
        socket.addEventListener('message', (message) => {
          if (typeof message.data !== 'string') return;
          try {
            const event = JSON.parse(message.data);
            const payload = event.payload ?? event;
            if (['ready', 'transcript', 'call_message_confirmed', 'call_message_rejected', 'ended'].includes(event.type)) {
              evidence.received.push({ path, type: event.type, messageId: payload.message_id,
                chatId: payload.chat_id, role: payload.role, revision: payload.revision });
            }
          } catch { /* Binary/provider audio is irrelevant to ciphertext proof. */ }
        });
        return socket;
      },
    });
    const originalCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await originalCapture(constraints);
      evidence.tracks.push(...stream.getTracks());
      return stream;
    };
  });
}

async function evidence(page: Page): Promise<Omit<CallEvidence, 'tracks'>> {
  return page.evaluate(() => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    return { sent: state.sent, received: state.received };
  });
}

async function holdChatLookup(page: Page, chatId: string): Promise<void> {
  await page.evaluate((boundChatId) => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    const originalGet = IDBObjectStore.prototype.get;
    const success = Object.getOwnPropertyDescriptor(IDBRequest.prototype, 'onsuccess');
    if (!success?.set || !success.get) throw new Error('Native IndexedDB success handler unavailable');
    let holding = true;
    const callbacks: Array<() => void> = [];
    state.heldChatLookupCount = 0;
    state.releaseChatLookup = () => {
      holding = false;
      IDBObjectStore.prototype.get = originalGet;
      for (const callback of callbacks.splice(0)) callback();
    };
    IDBObjectStore.prototype.get = function (key) {
      const request = originalGet.call(this, key);
      if (this.name === 'chats' && key === boundChatId) {
        Object.defineProperty(request, 'onsuccess', {
          configurable: true,
          get: () => success.get!.call(request),
          set: (handler: ((this: IDBRequest, event: Event) => unknown) | null) => {
            success.set!.call(request, (event: Event) => {
              if (!handler) return;
              if (holding) {
                state.heldChatLookupCount = (state.heldChatLookupCount ?? 0) + 1;
                callbacks.push(() => handler.call(request, event));
              } else handler.call(request, event);
            });
          },
        });
      }
      return request;
    };
  }, chatId);
}

test.describe('Integrated voice-call foundation', () => {
  // contract-test: direct surface=gui.web assertions=video-call.privacy
  test('refuses an unauthenticated call before opening a provider session', async ({ page }) => {
    const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL;
    expect(apiUrl, 'isolated CI must supply its private API URL').toBeTruthy();
    await page.goto('/');
    const result = await page.evaluate((url) => new Promise<{ ready: boolean; closed: boolean }>((resolve) => {
      const socket = new WebSocket(`${url.replace(/^http/, 'ws')}/v1/voice-call`);
      let ready = false;
      const timeout = setTimeout(() => { socket.close(); resolve({ ready, closed: false }); }, 10_000);
      socket.addEventListener('message', (event) => {
        try { ready ||= JSON.parse(event.data).type === 'ready'; } catch { /* A refusal has no provider content. */ }
      });
      socket.addEventListener('close', () => { clearTimeout(timeout); resolve({ ready, closed: true }); });
    }), apiUrl!);
    expect(result).toEqual({ ready: false, closed: true });
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding,video-call.chat.transcripts,video-call.chat.typed-input,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing,video-call.privacy
  test('saves voice and typed turns encrypted, reloads them and reuses their context', async ({ page }, testInfo) => {
    test.setTimeout(300_000);
    await observeRealTransport(page);
    // A fresh account opens the welcome workspace; the voice button creates
    // its chat without requiring a text draft or a visible editor first.
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-status"]:visible')).toContainText('Listening', { timeout: 45_000 });
    await expect(page.getByTestId('message-user').filter({ hasText: USER_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    await expect.poll(async () => {
      const bar = await page.locator('[data-testid="voice-call-bar"]:visible').boundingBox();
      const history = await page.locator('[data-testid="chat-history-container"]:visible').boundingBox();
      return bar && history ? history.y - (bar.y + bar.height) : Number.NEGATIVE_INFINITY;
    }).toBeGreaterThanOrEqual(-1);
    const chatId = await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
    expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
    // Collapsed recording is hidden; an expanded composer's control is disabled.
    await expect(page.locator('[data-testid="record-audio-button"]:visible:enabled, [data-testid="guest-cta-mic-button"]:visible:enabled')).toHaveCount(0);

    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-mute"]:visible')).toHaveAttribute('aria-pressed', 'true');
    const micCount = (await evidence(page)).sent.filter((event) => event.type === 'mic_audio').length;
    await page.waitForTimeout(350);
    expect((await evidence(page)).sent.filter((event) => event.type === 'mic_audio').length).toBe(micCount);

    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await expect(editor).toBeVisible();
    await editor.click();
    await expect(page.getByTestId('record-audio-button')).toBeDisabled();
    await page.keyboard.insertText(PASTED_TEXT);
    await page.evaluate(() => {
      (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.reconnectOnText = true;
    });
    await page.getByTestId('composer-send-button').click();
    await expect(page.getByTestId('message-user').filter({ hasText: PASTED_TEXT })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'I received your text' })).toHaveCount(1);
    await expect.poll(async () => (await evidence(page)).received.filter((event) => event.type === 'call_message_confirmed').length).toBeGreaterThanOrEqual(4);
    const transport = await evidence(page);
    const persisted = transport.sent.filter((event) => event.type === 'call_message_completed');
    expect(persisted.every((event) => (event.ciphertextLength ?? 0) > 30 && event.plaintext === false)).toBe(true);
    expect(transport.sent.filter((event) => event.type === 'text_input')).toHaveLength(1);
    expect(transport.sent.filter((event) => event.type === 'chat_message_added')).toHaveLength(0);
    expect(transport.received.filter((event) => event.type === 'call_message_rejected')).toHaveLength(0);
    expect(await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.reconnectInjected)).toBe(true);

    const messageIds = [...new Set(persisted.map((event) => event.messageId).filter((id): id is string => !!id))];
    expect(messageIds).toHaveLength(4);
    const rows = await page.evaluate(async (ids) => {
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const open = indexedDB.open('chats_db');
        open.onsuccess = () => resolve(open.result);
        open.onerror = () => reject(open.error);
      });
      try {
        return await Promise.all(ids.map((id) => new Promise<{ encrypted: boolean; plaintext: boolean }>((resolve, reject) => {
          const request = database.transaction('messages', 'readonly').objectStore('messages').get(id);
          request.onsuccess = () => resolve({ encrypted: typeof request.result?.encrypted_content === 'string',
            plaintext: typeof request.result?.content === 'string' });
          request.onerror = () => reject(request.error);
        })));
      } finally { database.close(); }
    }, messageIds);
    expect(rows.every((row) => row.encrypted && !row.plaintext)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('voice-call-laptop.png') });

    // Native workspace navigation must leave one accessible call-control owner.
    await page.evaluate(() => { window.location.hash = 'tasks'; });
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(1);
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveClass(/compact/);
    await expect(page.locator('[data-testid="voice-call-hangup"]:visible')).toBeVisible();
    // A pending native database read must not remove the only call controls.
    // Hold callback delivery, preserving the real request and its stored result.
    await holdChatLookup(page, chatId!);
    try {
      await page.locator('[data-testid="voice-call-return"]:visible').click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
        .__voiceCallEvidence.heldChatLookupCount ?? 0)).toBeGreaterThan(0);
      await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(1);
      await expect(page.locator('[data-testid="voice-call-hangup"]:visible')).toBeVisible();
    } finally {
      await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
        .__voiceCallEvidence.releaseChatLookup?.());
    }
    await expect(page.getByTestId('message-user').filter({ hasText: PASTED_TEXT })).toHaveCount(1);
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(1);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#settings-menu-toggle').click();
    await expect(page.getByTestId('settings-menu')).toHaveClass(/visible/);
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(1);
    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-mute"]:visible')).toHaveAttribute('aria-pressed', 'false');
    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    await page.locator('[data-testid="voice-call-return"]:visible').click();
    await expect(page.getByTestId('settings-menu')).not.toHaveClass(/visible/);
    await page.screenshot({ path: testInfo.outputPath('voice-call-phone.png') });

    await page.locator('[data-testid="voice-call-hangup"]:visible').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.tracks.every((track) => track.readyState === 'ended'))).toBe(true);
    await page.reload();
    await expect(page.getByTestId('message-user').filter({ hasText: USER_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-user').filter({ hasText: PASTED_TEXT })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'I received your text' })).toHaveCount(1);
    // A reloaded phone uses the collapsed composer's native recording control.
    await expect(page.getByRole('button', { name: 'Record audio', exact: true })).toBeEnabled();

    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-status"]:visible')).toContainText('Listening', { timeout: 45_000 });
    const resumed = (await evidence(page)).sent.find((event) => event.type === 'start');
    expect(resumed?.chatId).toBe(chatId);
    expect(resumed?.context?.some((turn) => turn.role === 'user' && turn.text.includes(PASTED_TEXT))).toBe(true);
    await page.locator('[data-testid="voice-call-hangup"]:visible').click();
  });
});
