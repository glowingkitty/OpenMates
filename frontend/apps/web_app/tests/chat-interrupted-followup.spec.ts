/* eslint-disable @typescript-eslint/no-require-imports */
/** Real disposable backend cancellation and encrypted recovery; no provider calls. */
import type { AITypingStartedPayload } from "../../../packages/ui/src/types/chat";
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, waitForChatReady, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { waitForContextSyncComplete, openChatAfterContextSync } = require('./helpers/chat-hydration');
const { email, password, otpKey } = getTestAccount();
const root = path.resolve(__dirname, '../../../..');

// New spec registration is candidate source, while the runner harness remains
// separately frozen. Reuse its existing guarded transition from this candidate
// so this regression always exercises recovery, even before registration lands.
function ensureIsolatedRecoveryEpoch(): void {
  expect(process.env.GITHUB_ACTIONS).toBe('true');
  expect(process.env.RUNNER_ENVIRONMENT).toBe('github-hosted');
  const compose = path.join(root, 'test-results/ci-private/compose.json');
  const profile = JSON.parse(fs.readFileSync(compose, 'utf8'));
  expect(profile.networks.default.internal).toBe(true);
  expect(profile.services.api.environment.OPENMATES_CI_ISOLATED).toBe('1');
  expect(profile.services.api.environment.OPENMATES_CI_AI_FIXTURES).toBe('1');
  const probe = `
import asyncio,json,logging,os
logging.disable(logging.CRITICAL)
assert os.getenv('OPENMATES_CI_ISOLATED') == '1' and os.getenv('MOCK_EXTERNAL_APIS') == 'true'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
async def main():
    cache=CacheService(); directus=DirectusService(cache_service=cache)
    try:
        print(json.dumps(await ChatRecoveryCutoverController(cache,directus).get_state(authoritative=True)))
    finally:
        await directus.close(); await cache.close()
asyncio.run(main())
`;
  const readState = () => JSON.parse(execFileSync('docker', ['compose', '-f', compose, 'exec', '-T',
    'api', 'python', '-c', probe], { cwd: root, encoding: 'utf8', timeout: 60_000 }).trim().split('\n').at(-1));
  let state = readState();
  if (state.protocol_epoch === 0) {
    execFileSync('python3', ['-c',
      "import sys; sys.path.insert(0, 'scripts'); from ci_run_tests import activate_isolated_marker_chat_epoch; activate_isolated_marker_chat_epoch('chat-interrupted-followup.spec.ts')"],
    { cwd: root, env: { ...process.env, OPENMATES_CI_SOURCE_ROOT: root }, encoding: 'utf8', timeout: 90_000 });
    state = readState();
  }
  expect(state).toEqual({ protocol_epoch: 1, sends_paused: false, legacy_in_flight: 0 });
}

test.describe('Interrupted personal chat follow-ups', () => {
  test.describe.configure({ timeout: 240_000 });
  skipWithoutCredentials(test, email, password, otpKey);
  test.beforeAll(() => ensureIsolatedRecoveryEpoch());
  for (const partial of [true, false]) {
    // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced,chats.completion.recovery-takeover,chat-processing-feedback.turn-lifecycle
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
        // The second send waits locally for the first encrypted completion.
        expect(frames.filter(f => f.direction === 'sent' && ['chat_message_added', 'chat_turn_admit'].includes(f.type)
          && (f.payload?.message?.message_id ?? f.payload?.message_id) === followupId)).toHaveLength(0);
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
