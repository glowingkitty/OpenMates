/**
 * Web job runner of chat orchestration (`chat_orchestration_jobs` capability),
 * flag-on builds only. Plan: docs/plans/chat-orchestration-main-chats/plan.yml.
 *
 * The Rust core decides everything (job parsing, link verification, effects,
 * bounded reads, claim/result frames: crypto/orchestrationOps.ts). This module
 * only performs the IO of the planned effect: create/send in a chat through the
 * normal send path, store a system event, read decrypted local messages.
 */
import { setChatOrchestrationJobsCapabilityEnabled } from '../../../config/api';
import { chatDB } from '../../db';
import { webSocketService } from '../../websocketService';
import { storeSystemEvent } from '../../contextEntryEvents';
import {
  createBackgroundChatWithPrompt, sendBackgroundChatMessage,
} from '../../forkChatService';
import {
  orchestrationBoundRead, orchestrationClaimFrame, orchestrationParseJob, orchestrationPlan,
  orchestrationResultFrame, type OrchestrationEffect, type OrchestrationJob, type OrchestrationStoreEvent,
} from '../crypto/orchestrationOps';

const FRAMES = ['chat_orchestration_job_available', 'chat_orchestration_job_claim_result', 'chat_orchestration_job_result_ack'] as const;

/** Jobs claimed here and waiting for the server's claim answer. */
const pending = new Map<string, { job: OrchestrationJob; effect: OrchestrationEffect }>();

/** The core frame helpers return the payload only; the type is fixed per direction. */
async function sendClaim(jobId: string): Promise<void> {
  await webSocketService.sendMessage('chat_orchestration_job_claim', await orchestrationClaimFrame(jobId));
}

async function sendResult(payload: Record<string, unknown>): Promise<void> {
  await webSocketService.sendMessage('chat_orchestration_job_result', payload);
}

function storeEvent(event: OrchestrationStoreEvent): Promise<boolean> {
  return storeSystemEvent(event.chat_id, event.message_id, event.content, event.created_at);
}

/** The creator link stored on a local chat; null when absent or the chat is unknown. */
async function localCreatorChatId(job: OrchestrationJob): Promise<string | null> {
  const chatId = (job.payload as { spawned_chat_id?: unknown } | null)?.spawned_chat_id;
  if (job.kind !== 'read_chat' && job.kind !== 'send_message') return null;
  if (typeof chatId !== 'string') return null;
  return (await chatDB.getChat(chatId))?.creator_chat_id ?? null;
}

async function readChat(chatId: string, limit: number): Promise<unknown> {
  const messages = await chatDB.getMessagesForChat(chatId);
  const mapped = messages
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .map((message) => ({
      role: message.role,
      content: typeof message.content === 'string' ? message.content : '',
      created_at: message.created_at,
    }));
  return orchestrationBoundRead(mapped, limit);
}

/** Performs one granted effect; resolves the result frame to send. */
async function perform(jobId: string, effect: OrchestrationEffect): Promise<Record<string, unknown>> {
  switch (effect.kind) {
    case 'start_chat':
      await createBackgroundChatWithPrompt({
        chatId: effect.chat_id, prompt: effect.brief, senderName: effect.sender_name,
        creatorChatId: effect.creator_chat_id, orchestrationJobId: effect.job_id,
      });
      await storeEvent(effect.started_event);
      return orchestrationResultFrame(effect.job_id, true);
    case 'store_event':
      await storeEvent(effect);
      return orchestrationResultFrame(jobId, true);
    case 'read_chat':
      return orchestrationResultFrame(effect.job_id, true, undefined, await readChat(effect.chat_id, effect.limit));
    case 'send_message':
      await sendBackgroundChatMessage(effect.chat_id, effect.text, {
        senderName: effect.sender_name, orchestrationJobId: effect.job_id,
      });
      return orchestrationResultFrame(effect.job_id, true);
    case 'reject':
      return orchestrationResultFrame(effect.job_id, false, effect.error_code);
  }
}

async function onAvailable(payload: unknown): Promise<void> {
  const job = await orchestrationParseJob(payload);
  if (!job) return;
  const effect = await orchestrationPlan(job, await localCreatorChatId(job));
  pending.set(job.job_id, { job, effect });
  await sendClaim(job.job_id);
}

async function onClaimResult(payload: unknown): Promise<void> {
  const { job_id: jobId, granted } = payload as { job_id: string; granted: boolean };
  const entry = pending.get(jobId);
  if (!entry) return;
  pending.delete(jobId);
  if (!granted) return;
  try {
    await sendResult(await perform(jobId, entry.effect));
  } catch (error) {
    console.error('[ChatOrchestration] Effect failed', error);
    await sendResult(await orchestrationResultFrame(jobId, false, 'job_failed'));
  }
}

/** Registers the frame handlers and advertises `chat_orchestration_jobs`. Returns the uninstall function. */
export function installChatOrchestrationJobRunner(): () => void {
  const handlers: Array<[string, (payload: unknown) => void]> = [
    [FRAMES[0], (payload) => void onAvailable(payload).catch((error) => console.error('[ChatOrchestration] job failed', error))],
    [FRAMES[1], (payload) => void onClaimResult(payload).catch((error) => console.error('[ChatOrchestration] claim failed', error))],
    [FRAMES[2], () => undefined],
  ];
  for (const [kind, handler] of handlers) webSocketService.on(kind, handler);
  setChatOrchestrationJobsCapabilityEnabled(true);
  if (webSocketService.isConnectedOrConnecting()) webSocketService.forceReconnect('Chat orchestration job runner installed');
  return () => {
    for (const [kind, handler] of handlers) webSocketService.off(kind, handler);
    setChatOrchestrationJobsCapabilityEnabled(false);
    pending.clear();
  };
}
