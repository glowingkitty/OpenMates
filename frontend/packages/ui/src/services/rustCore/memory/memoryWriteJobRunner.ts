/**
 * Web job runner of assistant Memory writes (`memory_write_jobs` capability),
 * flag-on builds only. Plan: docs/plans/assistant-memory-writes/plan.yml (TASK-3).
 *
 * The Rust core owns the protocol (claim, write, notice, result), Memory
 * validation, settings encryption, rollback and Undo rules
 * (memory_write_jobs.rs, memory_write_job_bridge.rs). This module only feeds
 * inbound frames to the crypto unit and performs the IO effects it returns:
 * POST the encrypted settings, store the notice through the existing
 * system-message path and wait for the server confirmation, and send the
 * frames. Undo posts the core-prepared settings and stores the core-built
 * undone marker, which keeps the notice undone after a reload.
 */
import { get } from 'svelte/store';
import { getApiEndpoint, setMemoryWriteJobsCapabilityEnabled } from '../../../config/api';
import { userProfile, updateProfile } from '../../../stores/userProfile';
import { getKeyFromStorage } from '../../cryptoService';
import { webSocketService } from '../../websocketService';
import { storeSystemEvent } from '../../contextEntryEvents';
import { rustWebCrypto, type WebCryptoClient } from '../crypto/webCryptoClient';
import {
  memoryJobFrame, memoryJobResume, memoryUndoPrepare,
  type MemoryJobEffect, type MemoryJobStep, type MemoryUndoPrepared,
} from '../crypto/memoryOps';
import type { ContextEntryHistoryEvent } from '../../../types/recommendations';

const JOB_FRAMES = ['memory_write_job_available', 'memory_write_job_claim_result', 'memory_write_job_result_ack'] as const;
/** The core's notice deadline; the server waits 20 s for the result. */
const NOTICE_CONFIRM_TIMEOUT_MS = 10_000;

const nowSeconds = () => Math.floor(Date.now() / 1000);

function cryptoClient(): WebCryptoClient {
  const client = rustWebCrypto();
  if (!client) throw new Error('rust_core_unavailable');
  return client;
}

async function masterKey(): Promise<CryptoKey> {
  const key = await getKeyFromStorage();
  if (!key) throw new Error('rule_settings_unavailable');
  return key;
}

/** POSTs core-encrypted settings; resolves null or the core's error code. */
async function postSettings(encryptedSettings: string): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(getApiEndpoint('/v1/settings/encrypted-account'), {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ encrypted_settings: encryptedSettings }),
    });
  } catch (error) {
    console.warn('[MemoryWrites] Settings upload did not reach the server', error);
    return 'offline';
  }
  if (response.status === 401 || response.status === 403) return 'rule_auth_required';
  if (!response.ok) return 'rule_save_failed';
  updateProfile({ encrypted_settings: encryptedSettings });
  return null;
}

/**
 * Resolves once the server confirmed `messageId`, rejects after the deadline.
 * Listens to the raw frame event, which fires on receipt: typed handlers of a
 * frame run one after another, so a slow or stuck earlier handler of
 * `system_message_confirmed` must not hold back this deadline-bound receipt.
 */
function confirmed(messageId: string): { promise: Promise<void>; cancel: () => void } {
  let cancel = () => {};
  const promise = new Promise<void>((resolve, reject) => {
    const listener = (event: Event) => {
      const frame = (event as CustomEvent<{ type?: unknown; payload?: { message_id?: unknown } | null }>).detail;
      if (frame?.type !== 'system_message_confirmed' || frame.payload?.message_id !== messageId) return;
      cancel();
      resolve();
    };
    const timer = setTimeout(() => { cancel(); reject(new Error('notice_unconfirmed')); }, NOTICE_CONFIRM_TIMEOUT_MS);
    cancel = () => { clearTimeout(timer); webSocketService.removeEventListener('message', listener); };
    webSocketService.addEventListener('message', listener);
  });
  return { promise, cancel };
}

async function perform(effect: MemoryJobEffect): Promise<string | null> {
  if (effect.kind === 'post_settings') return postSettings(effect.encrypted_settings);
  const confirmation = confirmed(effect.message_id);
  try {
    const stored = await storeSystemEvent(effect.chat_id, effect.message_id, effect.content, nowSeconds(),
      { userMessageId: effect.user_message_id });
    if (!stored) { confirmation.cancel(); return null; }
    await confirmation.promise;
    return null;
  } catch (error) {
    confirmation.cancel();
    console.error('[MemoryWrites] Could not store the Memory notice', error);
    return 'notice_failed';
  }
}

async function handleFrame(kind: string, payload: unknown): Promise<void> {
  const client = cryptoClient();
  let step: MemoryJobStep = await memoryJobFrame(
    client, await masterKey(), get(userProfile).encrypted_settings ?? null, kind, payload, nowSeconds());
  while ('token' in step) {
    step = await memoryJobResume(client, step.token, await perform(step.effect));
  }
  for (const [type, frame] of step.done.frames) await webSocketService.sendMessage(type, frame);
}

/**
 * Registers the frame handlers and advertises `memory_write_jobs` (reconnects an
 * open socket so the server sees the capability). Returns the uninstall function.
 */
export function installMemoryWriteJobRunner(): () => void {
  const handlers = JOB_FRAMES.map((kind) => {
    // Never awaited inside the socket dispatch: the notice waits for a later frame.
    const handler = (payload: unknown) => {
      void handleFrame(kind, payload).catch((error) => console.error(`[MemoryWrites] ${kind} failed`, error));
    };
    webSocketService.on(kind, handler);
    return [kind, handler] as const;
  });
  setMemoryWriteJobsCapabilityEnabled(true);
  // Also while connecting: that attempt's URL was built without the capability,
  // and the server would then drop every assistant Memory write of the session.
  if (webSocketService.isConnectedOrConnecting()) webSocketService.forceReconnect('Memory write job runner installed');
  return () => {
    for (const [kind, handler] of handlers) webSocketService.off(kind, handler);
    setMemoryWriteJobsCapabilityEnabled(false);
    void rustWebCrypto()?.call('memoryJobsClear').catch((error: unknown) =>
      console.warn('[MemoryWrites] Could not clear the core job state', error));
  };
}

/**
 * Undo of the assistant write `event` announces in chat `chatId`. Rejects with the
 * core code (`rule_changed` when the Memory was edited since, `rule_not_found`, ...).
 */
export async function undoAssistantMemoryWrite(chatId: string, event: ContextEntryHistoryEvent): Promise<MemoryUndoPrepared['outcome']> {
  const prepared = await memoryUndoPrepare(
    cryptoClient(), await masterKey(), get(userProfile).encrypted_settings ?? null, event, nowSeconds());
  const failure = await postSettings(prepared.encrypted_settings);
  if (failure) throw new Error(failure);
  await storeSystemEvent(chatId, prepared.marker_id, prepared.marker, nowSeconds());
  return prepared.outcome;
}
