/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Exercises authenticated queue admission and stable encrypted revisions.
 * Uses only the disposable GitHub CI API, cache, and committed mock seed.
 * Checks cross-device state, authorization, and the real CLI queued receipt.
 * Retains browser and terminal recordings; never runs against shared dev.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const {
  loginToTestAccount, waitForChatReady, sendMessage, waitForAssistantMessage,
  deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { openChatAfterContextSync, clickReadyComposerSend } = require('./helpers/chat-hydration');
const {
  createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome,
  workflowApiUrl, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

const root = path.resolve(__dirname, '../../../..');
const compose = path.join(root, 'test-results/ci-private/compose.json');
const { email, password, otpKey } = getTestAccount();

type ProtocolFrame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };

// Keep only renderer error codes and function names. Error messages and source
// URLs can contain private account or chat data and must not enter attachments.
type RendererErrorDiagnostic = { name: string; code: string | null; functions: string[];
  locations: Array<{ file: string; line: number; column: number }> };
function rendererErrorDiagnostic(error: Error): RendererErrorDiagnostic {
  const name = ['Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError'].includes(error.name)
    ? error.name : 'OtherError';
  const code = error.message.match(/\b(effect_update_depth_exceeded|state_unsafe_mutation|derived_references_self|each_key_duplicate|hydration_mismatch|effect_orphan|effect_in_teardown|rune_outside_svelte)\b/)?.[1] ?? null;
  const functions = (error.stack ?? '').split('\n').slice(1).flatMap((line) => {
    const frame = line.match(/^\s*at\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(/)?.[1];
    return frame ? [frame] : [];
  }).slice(0, 12);
  const locations = (error.stack ?? '').split('\n').slice(1).flatMap((line) => {
    const match = line.match(/([A-Za-z0-9_.-]{1,100}\.(?:js|ts|svelte))(?:\?[^\s():]*)?:(\d+):(\d+)\)?\s*$/);
    return match ? [{ file: match[1], line: Number(match[2]), column: Number(match[3]) }] : [];
  }).slice(0, 12);
  return { name, code, functions, locations };
}

function captureQueueFrames(page: any, frames: ProtocolFrame[]): { url: () => string | null } {
  let socketUrl: string | null = null;
  page.on('websocket', (socket: any) => {
    if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
    socketUrl = socket.url();
    const capture = (direction: ProtocolFrame['direction']) => (frame: { payload?: string }) => {
      try {
        const message = JSON.parse(String(frame.payload || ''));
        if (typeof message.type === 'string' && message.payload && typeof message.payload === 'object') {
          frames.push({ direction, type: message.type, payload: message.payload });
        }
      } catch { /* Ignore non-JSON control frames. */ }
    };
    socket.on('framesent', capture('sent'));
    socket.on('framereceived', capture('received'));
  });
  return { url: () => socketUrl };
}

function activeTaskFixture(chatId: string, operation: 'set' | 'clear'): void {
  expect(fs.existsSync(compose), 'Requires disposable coordinator compose').toBe(true);
  const program = `
import asyncio,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    try:
        metadata=await directus.chat.get_chat_metadata(data['chat_id'])
        assert metadata and metadata.get('id') == data['chat_id'], 'Test chat must exist before task fencing'
        if data['operation'] == 'set':
            for _ in range(40):
                if not await cache.get_active_ai_task(data['chat_id']): break
                await asyncio.sleep(.25)
            assert not await cache.get_active_ai_task(data['chat_id']), 'Seed mock task must finish before fixture marker'
            assert await cache.set_active_ai_task(data['chat_id'], 'queued-protocol-fixture-task', ttl=600)
        else:
            await cache.clear_active_ai_task(data['chat_id'])
        print('queue fixture applied')
    finally:
        await directus.close(); await cache.close()
asyncio.run(main())
`;
  const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e',
    'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
    cwd: root, input: JSON.stringify({ chat_id: chatId, operation }), encoding: 'utf8', timeout: 60_000
  });
  expect(output.trim()).toBe('queue fixture applied');
}

function validateQueuedWorkerScope(chatId: string): void {
  const program = `
import asyncio,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
from backend.core.api.app.services.cache import CacheService
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks.ask_skill_task import _validated_queued_messages, _validated_recovery_queued_member
async def main():
    chat_id=json.load(sys.stdin)['chat_id']; cache=CacheService()
    try:
        client=await cache.client
        raw=await client.lrange(f'chat:{chat_id}:message_queue',0,19)
        assert len(raw) == 1, 'Expected the actual admitted WebSocket queue member'
        members=[json.loads(row) for row in raw]
        assert members[0].get('is_external') is False
        assert members[0].get('is_anonymous') is False
        request=AskSkillRequest.model_validate(members[0])
        scope=('chat_id','user_id','user_id_hash','is_incognito','is_external','is_anonymous',
               'team_id','team_id_hash','team_workspace_type','team_object_id_hash')
        assert all(members[0].get(field) == getattr(request,field) for field in scope)
        lease={'messages':members,'raw_messages':raw}
        if request.recovery_task_id:
            validated=_validated_recovery_queued_member(lease)
            assert validated.message_id == request.message_id
        else:
            ids,_=_validated_queued_messages(request,lease)
            assert ids == [request.message_id]
        print('queued worker scope validated')
    finally:
        await cache.close()
asyncio.run(main())
`;
  const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e',
    'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
    cwd: root, input: JSON.stringify({ chat_id: chatId }), encoding: 'utf8', timeout: 60_000
  });
  expect(output.trim()).toBe('queued worker scope validated');
}

async function requestQueueEvent(page: any, url: string, type: string,
  payload: Record<string, unknown>, responseType: string): Promise<Record<string, any>> {
  return page.evaluate(async ({ url, type, payload, responseType }: {
    url: string; type: string; payload: Record<string, unknown>; responseType: string;
  }) => {
    const dedicatedUrl = new URL(url);
    dedicatedUrl.searchParams.set('sessionId', `queued-protocol-${crypto.randomUUID()}`);
    return new Promise<Record<string, any>>((resolve, reject) => {
      const socket = new WebSocket(dedicatedUrl);
      const timeout = setTimeout(() => { socket.close(); reject(new Error(`${responseType} timed out`)); }, 20_000);
      socket.addEventListener('open', () => socket.send(JSON.stringify({ type, payload })), { once: true });
      socket.addEventListener('message', (event) => {
        let message: { type?: string; payload?: Record<string, any> };
        try { message = JSON.parse(String(event.data)); } catch { return; }
        if (message.type !== responseType) return;
        clearTimeout(timeout); socket.close(); resolve(message.payload ?? {});
      });
      socket.addEventListener('close', (event) => {
        clearTimeout(timeout);
        if (!event.wasClean) reject(new Error(`${responseType} socket closed before ACK`));
      });
    });
  }, { url, type, payload, responseType });
}

test.describe('Queued follow-up authenticated protocol', () => {
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
    || process.env.CI_TEST_MODE !== 'e2e' || !process.env.E2E_USE_MOCKS,
  'Requires isolated GitHub product stack and deterministic mock inference');
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision,chat-queued-followups.steering.safe-boundary,chat-queued-followups.access.scoped
  // contract-test: supporting surface=rest_api assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision,chat-queued-followups.steering.safe-boundary,chat-queued-followups.access.scoped
  // contract-test: direct surface=cli assertions=chat-queued-followups.admission.synced
  test('server queues one encrypted turn, fences revisions and shares its state across connections', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
    const frames: ProtocolFrame[] = [];
    const transport = captureQueueFrames(page, frames);
    let chatId: string | null = null;
    let markerSet = false;
    let otherTab: any = null;
    let otherContext: any = null;
    let peerPhase = 'login';
    const peerRendererErrors: Array<RendererErrorDiagnostic & { phase: string }> = [];
    const peerConsoleErrors: Array<RendererErrorDiagnostic & { phase: string; component: string | null }> = [];
    const peerConsoleCaptures: Promise<void>[] = [];
    try {
      await loginToTestAccount(page);
      await waitForChatReady(page);
      // A new-chat seed needs the initial personal-context snapshot to finish.
      await expect.poll(() => page.evaluate(async () => {
        const state = await (window as any).__openmatesE2EChatConnectionState?.();
        return state?.online === true && state?.websocketConnected === true
          && state?.cachePrimed === true && state?.contextSyncCompleted === true
          && state?.teamContextActive === false;
      }), { timeout: 45_000 }).toBe(true);
      try {
        await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
      } catch (error) {
        const sendState = await page.evaluate(async () => {
          const browser = window as any;
          const preflight = browser.__openmatesLastPreflightDebug;
          const send = browser.__openmatesLastSendDebug;
          const failure = send?.step === 'send_failed' ? send?.details?.error : null;
          const sendSteps = new Set([
            'send_invoked', 'send_guard_acquired', 'draft_state_read',
            'deferred_scan_started', 'deferred_scan_complete', 'markdown_converted',
            'url_processing_started', 'url_processing_complete', 'url_processing_skipped_anonymous',
            'url_processing_failed', 'pii_detection_started', 'pii_detection_failed',
            'pii_detection_complete', 'suggestion_tracker_import_started',
            'suggestion_tracker_import_complete', 'suggestion_consumed',
            'session_state_checked', 'anonymous_send_path_started',
            'authenticated_send_path_started', 'send_chat_classification_started',
            'send_chat_classification_complete', 'send_aborted_created_chat_missing',
            'send_aborted_existing_chat_missing', 'send_aborted_chat_update_missing',
            'send_cancelled_before_dispatch', 'local_message_dispatch_started',
            'local_message_dispatched', 'send_cancelled_after_dispatch',
            'send_set_active_chat_started', 'send_set_active_chat_complete',
            'send_cancelled_before_websocket', 'send_new_message_started',
            'send_new_message_complete', 'sent_message_deleted_after_cancellation',
          ]);
          const previousStep = send?.details?.failedAfterStep;
          const name = typeof failure?.name === 'string' ? failure.name : '';
          const safeNames = new Set([
            'Error', 'TypeError', 'AbortError', 'InvalidStateError', 'NotAllowedError',
            'OperationError', 'TimeoutError', 'DataError', 'NotFoundError', 'QuotaExceededError'
          ]);
          const message = typeof failure?.message === 'string' ? failure.message : '';
          const sendErrorCategory = /encrypt|crypt|\bkey\b/i.test(message) ? 'crypto'
            : /draft/i.test(message) ? 'draft'
              : /preflight/i.test(message) ? 'preflight'
                : /websocket|network|offline/i.test(message) ? 'transport'
                  : /auth|token/i.test(message) ? 'auth' : 'other';
          // Match fixed source error phrases; never attach the raw error message or stack.
          const sendCryptoFailureCode = sendErrorCategory !== 'crypto' ? null
            : message.includes('persisted encrypted_chat_key could not be decrypted')
              ? 'persisted_chat_key_undecryptable'
              : message.includes('master key unavailable')
                ? 'master_key_unavailable'
                : message.includes('Chat encryption key mismatch prevented message storage')
                  ? 'chat_key_conflict'
                  : message.includes('no chat key available') ||
                      /Saved chat .+ has no (?:encrypted |safe )?chat key/.test(message)
                    ? 'saved_chat_key_missing'
                    : message.includes('Stored turn preflight cannot be decrypted with the current chat key')
                      ? 'preflight_undecryptable'
                      : 'crypto_other';
          return {
            transport: await browser.__openmatesE2EChatConnectionState?.(),
            preflightStep: preflight?.step === 'preflight_dispatch_started'
              || preflight?.step === 'preflight_dispatch_complete' ? preflight.step : null,
            sendStep: send?.step === 'send_failed' || sendSteps.has(send?.step) ? send.step : null,
            failedAfterStep: sendSteps.has(previousStep) ? previousStep : null,
            sendErrorName: failure ? (safeNames.has(name) ? name : 'other') : null,
            sendErrorCategory: failure ? sendErrorCategory : null,
            sendCryptoFailureCode: failure ? sendCryptoFailureCode : null,
            sendHasMessagePayload: send?.details?.hasMessagePayload === true,
            lastUserStatus: Array.from(document.querySelectorAll('[data-testid="message-user"]'))
              .at(-1)?.getAttribute('data-status') ?? null
          };
        }).catch(() => null);
        await testInfo.attach('initial-send-transport', {
          body: JSON.stringify({ sendState, frameTypes: frames.map(({ direction, type }) => ({ direction, type })) }),
          contentType: 'application/json'
        });
        throw error;
      }
      await waitForAssistantMessage(page, { which: 'last', timeout: 90_000 });
      await expect(page.getByTestId('typing-indicator')).toHaveCount(0, { timeout: 30_000 });
      chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
      expect(chatId).toBeTruthy();
      await expect.poll(() => transport.url()).not.toBeNull();
      activeTaskFixture(chatId!, 'set');
      markerSet = true;

      const otherFrames: ProtocolFrame[] = [];
      // Use independent browser storage and authentication for cross-device sync.
      otherContext = await browser.newContext({
        recordVideo: { dir: testInfo.outputPath('peer-video') }
      });
      otherTab = await otherContext.newPage();
      otherTab.on('pageerror', (error: Error) => {
        if (peerRendererErrors.filter((entry) => entry.phase === peerPhase).length < 20) {
          peerRendererErrors.push({ phase: peerPhase, ...rendererErrorDiagnostic(error) });
        }
      });
      otherTab.on('console', (message: any) => {
        if (message.type() !== 'error'
          || peerConsoleErrors.filter((entry) => entry.phase === peerPhase).length >= 20) return;
        const raw = message.text();
        const diagnostic = rendererErrorDiagnostic(Object.assign(new Error(raw), {
          name: raw.match(/\b(TypeError|RangeError|ReferenceError|SyntaxError)\b/)?.[1] ?? 'Error',
          stack: '' // A fallback Error created by Playwright has no browser frames.
        }));
        const entry = { phase: peerPhase,
          component: raw.match(/\[(ActiveChat|ChatHistory)\]/)?.[1] ?? null,
          ...diagnostic };
        peerConsoleErrors.push(entry);
        // Caught render failures may reach console.error as a separate Error
        // argument. Retain its sanitized frames too, without raw error text.
        peerConsoleCaptures.push((async () => {
          for (const argument of message.args().slice(0, 4)) {
            const value = await argument.evaluate((value: unknown) => value instanceof Error
              ? { name: value.name, message: value.message, stack: value.stack } : null).catch(() => null);
            if (value) {
              Object.assign(entry, rendererErrorDiagnostic(Object.assign(new Error(value.message), value)));
              break;
            }
          }
        })());
      });
      const otherTransport = captureQueueFrames(otherTab, otherFrames);
      // The server rejects reuse of a TOTP code from the same 30-second window.
      await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
      await loginToTestAccount(otherTab);
      await waitForChatReady(otherTab);
      await openChatAfterContextSync(otherTab, chatId!, testInfo);
      const peerActiveChat = otherTab.getByTestId('active-chat-container');
      await expect(peerActiveChat).toHaveAttribute('data-chat-load-state', 'ready');
      await expect(peerActiveChat).toHaveAttribute('data-current-message-count', '2');
      await expect(otherTab.getByTestId('message-user')).toHaveCount(1);
      await expect(otherTab.getByTestId('message-assistant')).toHaveCount(1);
      await expect.poll(() => otherTransport.url()).not.toBeNull();
      const ownerSession = new URL(transport.url()!).searchParams.get('sessionId');
      const peerSession = new URL(otherTransport.url()!).searchParams.get('sessionId');
      expect(Boolean(ownerSession && peerSession && ownerSession !== peerSession),
        'Owner and peer need distinct WebSocket connection identities').toBe(true);

      await sendMessage(page, 'A queued follow-up for the same chat.');
      await expect.poll(() => frames.find((frame) => frame.direction === 'received'
        && frame.type === 'message_queued' && frame.payload.chat_id === chatId), { timeout: 30_000 }).toBeTruthy();
      const queuedFrame = frames.find((frame) => frame.direction === 'received'
        && frame.type === 'message_queued' && frame.payload.chat_id === chatId)!;
      const messageId = queuedFrame.payload.user_message_id;
      expect(typeof messageId).toBe('string');
      expect(queuedFrame.payload.queue_revision).toBe(1);
      expect(queuedFrame.payload.queue_mode).toBe('follow_up');
      validateQueuedWorkerScope(chatId);
      await expect.poll(() => otherFrames.some((frame) => frame.type === 'queued_message_status'
        && frame.payload.user_message_id === messageId)).toBe(true);

      const row = page.locator(`[data-message-id="${messageId}"]`);
      await expect(row.getByTestId('queued-followup-status')).toHaveText('Queued');
      const peerRow = otherTab.locator(`[data-message-id="${messageId}"]`);
      try {
        await expect(peerRow.getByTestId('queued-followup-status')).toHaveText('Queued');
      } catch (error) {
        await testInfo.attach('peer-queue-sync-diagnostic', {
          body: JSON.stringify({
            distinctConnectionIdentities: Boolean(ownerSession && peerSession && ownerSession !== peerSession),
            newMessageFrame: otherFrames.some((frame) => frame.type === 'new_chat_message'
              && frame.payload.message_id === messageId),
            queuedStatusFrame: otherFrames.some((frame) => frame.type === 'queued_message_status'
              && frame.payload.user_message_id === messageId),
            peerRowCount: await peerRow.count(),
            senderRowCount: await row.count()
          }),
          contentType: 'application/json'
        });
        throw error;
      }

      const socketUrl = transport.url()!;
      const snapshot = await requestQueueEvent(page, socketUrl, 'get_queued_messages',
        { chat_id: chatId }, 'queued_messages_snapshot');
      expect(snapshot.messages).toEqual(expect.arrayContaining([{
        message_id: messageId, queue_mode: 'follow_up', queue_revision: 1
      }]));
      expect(JSON.stringify(snapshot)).not.toContain('A queued follow-up');

      const editor = page.getByTestId('message-editor').locator('.ProseMirror');
      const editBanner = page.getByTestId('queued-edit-banner');
      await row.getByTestId('queued-followup-edit').click();
      await expect(editBanner).toBeVisible();
      await expect(editor).toContainText('A queued follow-up for the same chat.');
      await clickReadyComposerSend(page);
      await expect(editBanner).toHaveCount(0);
      expect(frames.filter((frame) => frame.direction === 'sent'
        && frame.type === 'revise_queued_message' && frame.payload.message_id === messageId)).toHaveLength(0);
      const unchanged = await requestQueueEvent(page, socketUrl, 'get_queued_messages',
        { chat_id: chatId }, 'queued_messages_snapshot');
      expect(unchanged.messages).toEqual(snapshot.messages);

      await row.getByTestId('queued-followup-edit').click();
      await expect(editBanner).toBeVisible();
      await expect(editor).toContainText('A queued follow-up for the same chat.');
      await editor.fill('Revised queued follow-up from the owner');
      await expect(editBanner).toBeVisible();
      await expect(editor).toContainText('Revised queued follow-up from the owner');
      await clickReadyComposerSend(page);
      await expect.poll(() => frames.find((frame) => frame.type === 'queued_message_updated'
        && frame.payload.message_id === messageId && frame.payload.queue_revision === 2)).toBeTruthy();
      const editAck = frames.find((frame) => frame.type === 'queued_message_updated'
        && frame.payload.message_id === messageId && frame.payload.queue_revision === 2)!;
      expect(editAck.payload.encrypted_content).toBeTruthy();
      expect(editAck.payload.encrypted_content).not.toContain('Revised queued follow-up');
      await expect.poll(() => otherFrames.some((frame) => frame.type === 'queued_message_updated'
        && frame.payload.message_id === messageId && frame.payload.queue_revision === 2)).toBe(true);
      await expect(peerRow).toContainText('Revised queued follow-up from the owner');
      await expect(page.locator(`[data-message-id="${messageId}"]`)).toHaveCount(1);
      await expect(peerActiveChat).toHaveAttribute('data-current-message-count', '3');
      await expect(peerActiveChat).toHaveAttribute('data-current-message-chat-consistent', 'true');

      const stale = await requestQueueEvent(page, socketUrl, 'revise_queued_message', {
        chat_id: chatId, message_id: messageId, expected_revision: 1, queue_mode: 'steer'
      }, 'queued_message_revision_rejected');
      expect(stale.reason_code).toBe('conflict');
      expect(stale.current_revision).toBe(2);
      await expect(row.getByTestId('queued-followup-status')).toHaveText('Queued');

      const steer = await requestQueueEvent(page, socketUrl, 'revise_queued_message', {
        chat_id: chatId, message_id: messageId, expected_revision: 2, queue_mode: 'steer'
      }, 'queued_message_updated');
      expect(steer.queue_revision).toBe(3);
      expect(steer.queue_mode).toBe('steer');
      expect(steer.encrypted_content).toBe(editAck.payload.encrypted_content);
      await expect(peerRow.getByTestId('queued-followup-status')).toHaveText('Steering current response');

      peerPhase = 'reload';
      await otherTab.reload({ waitUntil: 'domcontentloaded' });
      await waitForChatReady(otherTab);
      await openChatAfterContextSync(otherTab, chatId!, testInfo);
      // Editing or changing the queued mode advances messages_v without adding a row.
      // The three canonical rows must still hydrate as a ready chat after reload.
      await expect(peerActiveChat).toHaveAttribute('data-chat-load-state', 'ready');
      await expect(peerActiveChat).toHaveAttribute('data-current-message-count', '3');
      await expect(peerActiveChat).toHaveAttribute('data-current-message-chat-consistent', 'true');
      await expect.poll(async () => Number(await peerActiveChat.getAttribute('data-current-chat-messages-version')))
        .toBeGreaterThan(3);
      const reloadedHistory = otherTab.getByTestId('chat-history-content');
      await expect(reloadedHistory).toHaveAttribute('data-source-message-count', '3');
      await expect(reloadedHistory).toHaveAttribute('data-rendered-message-count', '3');
      await expect(otherTab.getByTestId('message-user')).toHaveCount(2);
      await expect(otherTab.getByTestId('message-assistant')).toHaveCount(1);
      await expect(otherTab.locator(`[data-message-id="${messageId}"]`)).toContainText('Revised queued follow-up from the owner');
      await expect(otherTab.locator(`[data-message-id="${messageId}"]`).getByTestId('queued-followup-controls'))
        .toHaveAttribute('data-queue-mode', 'steer');
      const afterReload = await requestQueueEvent(page, socketUrl, 'get_queued_messages',
        { chat_id: chatId }, 'queued_messages_snapshot');
      expect(afterReload.messages).toEqual(expect.arrayContaining([{
        message_id: messageId, queue_mode: 'steer', queue_revision: 3
      }]));

      const foreign = await requestQueueEvent(page, socketUrl, 'get_queued_messages',
        { chat_id: randomUUID() }, 'queued_messages_snapshot');
      expect(foreign.messages).toEqual([]);
      const denied = await requestQueueEvent(page, socketUrl, 'revise_queued_message', {
        chat_id: randomUUID(), message_id: messageId, expected_revision: 3, queue_mode: 'follow_up'
      }, 'queued_message_revision_rejected');
      expect(['not_queued', 'forbidden']).toContain(denied.reason_code);

      const guestContext = await browser.newContext();
      try {
        const guestPage = await guestContext.newPage();
        await guestPage.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
        const guest = await guestPage.evaluate(async (observedUrl: { url: string; chatId: string }) => {
          const url = new URL(observedUrl.url);
          url.searchParams.delete('token');
          url.searchParams.set('sessionId', 'unauthenticated-queued-protocol');
          return new Promise<{ opened: boolean; closeCode: number }>((resolve) => {
            const socket = new WebSocket(url);
            let opened = false;
            const timeout = setTimeout(() => { socket.close(); resolve({ opened, closeCode: 0 }); }, 10_000);
            socket.addEventListener('open', () => {
              opened = true;
              socket.send(JSON.stringify({ type: 'get_queued_messages', payload: { chat_id: observedUrl.chatId } }));
            });
            socket.addEventListener('close', (event) => {
              clearTimeout(timeout); resolve({ opened, closeCode: event.code });
            });
          });
        }, { url: socketUrl, chatId });
        expect(guest.opened).toBe(false);
        expect([1008, 1006]).toContain(guest.closeCode);
      } finally { await guestContext.close(); }

      // The authenticated CLI shares the same owner queue and returns its queued
      // ACK without waiting for a model response. Keep its real terminal capture.
      const cliHome = createWorkflowCliHome('queued-protocol');
      // The pairing helper performs a login. Use independent storage rather
      // than racing an already-authenticated tab's session restoration.
      const cliContext = await browser.newContext({
        recordVideo: { dir: testInfo.outputPath('cli-pair-video') }
      });
      const cliPage = await cliContext.newPage();
      try {
        // This is a third login for the same account; the server consumes each
        // TOTP only once in its 30-second window, as with the peer login above.
        await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
        const apiUrl = workflowApiUrl();
        await loginWorkflowCliViaPair(cliPage, apiUrl, cliHome, 'QUEUED_PROTOCOL');
        installRecorderDeps();
        const cliResult = await runCli(apiUrl,
          ['chats', 'send', '--chat', chatId, 'CLI queued follow-up', '--json'], 90_000, {
            useApiKey: false,
            env: { ...workflowCliEnv(apiUrl, cliHome), OPENMATES_CLI_RECORD_E2E: '1',
              OPENMATES_E2E_SPEC: 'chat-queued-followups-protocol' }
          });
        expect(cliResult.recording?.videoPath && fs.existsSync(cliResult.recording.videoPath),
          'CLI queued-send terminal recording must exist').toBe(true);
        await testInfo.attach('queued-followup-cli-terminal-video', {
          path: cliResult.recording.videoPath, contentType: 'video/mp4'
        });
        if (cliResult.recording.manifestPath && fs.existsSync(cliResult.recording.manifestPath)) {
          await testInfo.attach('queued-followup-cli-terminal-manifest', {
            path: cliResult.recording.manifestPath, contentType: 'application/json'
          });
        }
        expect(cliResult.code, 'CLI queued send failed').toBe(0);
        // The recorded PTY includes stderr warnings before the stdout receipt.
        const cliJsonStart = cliResult.stdout.search(/^[ \t]*\{/m);
        expect(cliJsonStart, 'CLI queued send did not emit a JSON receipt').toBeGreaterThanOrEqual(0);
        const cliAck = (() => {
          try {
            return JSON.parse(cliResult.stdout.slice(cliJsonStart));
          } catch {
            throw new Error('CLI queued send emitted an invalid JSON receipt');
          }
        })();
        expect(cliAck.status).toBe('queued');
        expect(cliAck.chatId).toBe(chatId);
        expect(cliAck.userMessageId).toBeTruthy();
        expect(cliAck.queueRevision).toBe(1);
        const cliSnapshot = await requestQueueEvent(page, socketUrl, 'get_queued_messages',
          { chat_id: chatId }, 'queued_messages_snapshot');
        expect(cliSnapshot.messages).toEqual(expect.arrayContaining([{
          message_id: cliAck.userMessageId, queue_mode: 'follow_up', queue_revision: 1
        }]));
      } finally {
        try {
          const cliBrowserVideo = cliPage.video();
          await cliContext.close();
          if (cliBrowserVideo) await testInfo.attach('queued-followup-cli-pair-browser-video', {
            path: await cliBrowserVideo.path(), contentType: 'video/webm'
          });
        } finally { removeWorkflowCliHome(cliHome); }
      }
    } finally {
      // Retain this witness for every outcome, including failures after the
      // count assertions. DOM counts can update before row construction fails.
      if (otherTab && !otherTab.isClosed()) {
        await Promise.allSettled(peerConsoleCaptures);
        const active = otherTab.getByTestId('active-chat-container');
        const history = otherTab.getByTestId('chat-history-content');
        const attribute = (locator: any, name: string) => locator.getAttribute(name, { timeout: 1_000 }).catch(() => null);
        await testInfo.attach('peer-browser-render-diagnostic', {
          body: JSON.stringify({
            phase: peerPhase,
            parentCountOnPage: await active.count().catch(() => 0),
            historyCount: await history.count().catch(() => 0),
            historyInsideMeasuredParent: await active.getByTestId('chat-history-content').count().catch(() => 0),
            parentMatchesSelectedChat: Boolean(chatId && await attribute(active, 'data-current-chat-id') === chatId),
            childMatchesSelectedChat: Boolean(chatId && await attribute(history, 'data-current-chat-id') === chatId),
            historyBound: await attribute(active, 'data-chat-history-bound'),
            sourceCount: await attribute(history, 'data-source-message-count'),
            renderedCount: await attribute(history, 'data-rendered-message-count'),
            parentCount: await attribute(active, 'data-current-message-count'),
            parentReady: await attribute(active, 'data-chat-load-state'),
            renderedUserRows: await otherTab.getByTestId('message-user').count().catch(() => 0),
            renderedAssistantRows: await otherTab.getByTestId('message-assistant').count().catch(() => 0),
            rowTestIds: await history.locator('[data-message-id]').evaluateAll((nodes: Element[]) => nodes.map(node => {
              const value = node.getAttribute('data-testid') ?? '';
              return ['message-user', 'message-assistant', 'message-system', 'message-undefined', 'message-null'].includes(value)
                ? value : 'other';
            })).catch(() => []),
            persistedRows: await otherTab.evaluate(async (selectedChat: string | null) => {
              if (!selectedChat || !(await indexedDB.databases()).some(db => db.name === 'chats_db')) return null;
              return new Promise((resolve) => {
                const timeout = setTimeout(() => resolve(null), 2_000);
                const request = indexedDB.open('chats_db');
                request.onupgradeneeded = () => request.transaction?.abort();
                request.onerror = () => { clearTimeout(timeout); resolve(null); };
                request.onsuccess = () => {
                  const database = request.result;
                  try {
                    const rows = database.transaction('messages', 'readonly').objectStore('messages')
                      .index('chat_id').getAll(IDBKeyRange.only(selectedChat));
                    rows.onerror = () => { database.close(); clearTimeout(timeout); resolve(null); };
                    rows.onsuccess = () => {
                      const messages = rows.result;
                      const ids = messages.map(row => row.message_id);
                      database.close(); clearTimeout(timeout);
                      resolve({ count: messages.length, uniqueIds: new Set(ids).size,
                        missingIds: ids.filter(id => typeof id !== 'string' || !id).length,
                        roles: ['user', 'assistant', 'system'].map(role => ({ role,
                          count: messages.filter(row => row.role === role).length })),
                        otherRoles: messages.filter(row => !['user', 'assistant', 'system'].includes(row.role)).length });
                    };
                  } catch { database.close(); clearTimeout(timeout); resolve(null); }
                };
              });
            }, chatId).catch(() => null),
            rendererErrors: peerRendererErrors,
            consoleErrors: peerConsoleErrors
          }), contentType: 'application/json'
        });
        const peerScreenshot = testInfo.outputPath('queued-followup-peer-final.png');
        try {
          await otherTab.screenshot({ path: peerScreenshot, timeout: 5_000 });
          await testInfo.attach('queued-followup-peer-final', { path: peerScreenshot, contentType: 'image/png' });
        } catch {
          await testInfo.attach('peer-final-capture-unavailable', {
            body: 'Peer screenshot capture was unavailable during teardown.', contentType: 'text/plain'
          });
        }
      }
      const peerVideo = otherTab?.video();
      if (otherContext) await otherContext.close();
      if (peerVideo) await testInfo.attach('queued-followup-peer-video', {
        path: await peerVideo.path(), contentType: 'video/webm'
      });
      if (chatId && markerSet) activeTaskFixture(chatId, 'clear');
      if (chatId) await deleteActiveChat(page).catch(() => undefined);
    }
  });
});
