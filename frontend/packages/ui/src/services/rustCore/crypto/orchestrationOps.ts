/**
 * Chat orchestration ops of the crypto unit (`orchestration*` Worker exports,
 * packages/openmates-browser-bindings/src/browser_orchestration.rs).
 *
 * All rules (job validation and expiry, planning, the "only chats this chat
 * spawned" refusal, event content and lines, read bounds) run in the Rust core
 * (packages/openmates-rust/src/client/chat_orchestration.rs). The page only
 * performs the returned effects. Frame helpers return the frame payload; the
 * caller sends it under the `chat_orchestration_job_claim` / `_result` type.
 */
import { rustWebCrypto } from './webCryptoClient';
import type { WebCryptoOp } from './webCryptoClient';

export type OrchestrationOp =
  | 'orchestrationParseJob' | 'orchestrationPlan' | 'orchestrationClaimFrame' | 'orchestrationResultFrame'
  | 'orchestrationBoundRead' | 'orchestrationParseEvent' | 'orchestrationEventLine'
  | 'orchestrationCreatorFromSenderName';

/** Worker export behind each op; spread into the crypto unit's async export table. */
export const ORCHESTRATION_ASYNC_EXPORTS: Record<OrchestrationOp, string> = {
  orchestrationParseJob: 'orchestrationParseJob',
  orchestrationPlan: 'orchestrationPlan',
  orchestrationClaimFrame: 'orchestrationClaimFrame',
  orchestrationResultFrame: 'orchestrationResultFrame',
  orchestrationBoundRead: 'orchestrationBoundRead',
  orchestrationParseEvent: 'orchestrationParseEvent',
  orchestrationEventLine: 'orchestrationEventLine',
  orchestrationCreatorFromSenderName: 'orchestrationCreatorFromSenderName',
};

export type OrchestrationJob = { job_id: string; kind: 'start_chat'|'creator_event'|'read_chat'|'send_message'; payload: Record<string, unknown>; created_at: number; expires_at: number };
export type OrchestrationStoreEvent = { kind: 'store_event'; chat_id: string; message_id: string; content: string; created_at: number };
export type OrchestrationEffect =
  | { kind: 'start_chat'; chat_id: string; creator_chat_id: string; title: string; brief: string; sender_name: string; job_id: string; started_event: OrchestrationStoreEvent }
  | OrchestrationStoreEvent
  | { kind: 'read_chat'; chat_id: string; limit: number; job_id: string }
  | { kind: 'send_message'; chat_id: string; text: string; sender_name: string; job_id: string }
  | { kind: 'reject'; job_id: string; error_code: string };
export type OrchestrationEvent = { action: 'started'|'report'|'finished'|'waiting_for_user'|'user_wrote'; chat_id: string; title: string|null; text: string|null; event_id: string; created_at: number };

async function call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T> {
  const client = rustWebCrypto();
  if (!client) throw new Error('rust_core_unavailable');
  return client.call<T>(op, ...args);
}

/** Validates a `chat_orchestration_job_available` payload; null when invalid or expired. */
export async function orchestrationParseJob(payload: unknown): Promise<OrchestrationJob | null> {
  return JSON.parse(await call<string>(
    'orchestrationParseJob', JSON.stringify(payload ?? null), Math.floor(Date.now() / 1000)));
}

/** What the page must do for a validated job (`localCreatorChatId` = the stored creator link of the target chat). */
export async function orchestrationPlan(job: OrchestrationJob, localCreatorChatId: string | null): Promise<OrchestrationEffect> {
  return JSON.parse(await call<string>('orchestrationPlan', JSON.stringify(job), localCreatorChatId));
}

/** Payload of the `chat_orchestration_job_claim` frame. */
export async function orchestrationClaimFrame(jobId: string): Promise<Record<string, unknown>> {
  return JSON.parse(await call<string>('orchestrationClaimFrame', jobId));
}

/** Payload of the `chat_orchestration_job_result` frame. */
export async function orchestrationResultFrame(
  jobId: string, ok: boolean, errorCode?: string | null, result?: unknown,
): Promise<Record<string, unknown>> {
  return JSON.parse(await call<string>(
    'orchestrationResultFrame', jobId, ok, errorCode ?? null,
    result === undefined ? null : JSON.stringify(result)));
}

/** Bounds a `read_chat` result (last `limit` messages, 2000 chars each, 12000 total). */
export async function orchestrationBoundRead(
  messages: { role: string; content: string; created_at: number }[], limit: number,
): Promise<unknown> {
  return JSON.parse(await call<string>('orchestrationBoundRead', JSON.stringify(messages), limit));
}

/** Parses system message content; null when it is not a valid `chat_orchestration` event. */
export async function orchestrationParseEvent(content: string): Promise<OrchestrationEvent | null> {
  return JSON.parse(await call<string>('orchestrationParseEvent', content));
}

/** One-line English summary of an event; `resolvedTitle` wins over the stored title. */
export async function orchestrationEventLine(event: OrchestrationEvent, resolvedTitle: string | null): Promise<string> {
  return call<string>('orchestrationEventLine', JSON.stringify(event), resolvedTitle);
}

/** Creator chat id of a `chat:<uuid>` sender name, else null. */
export async function orchestrationCreatorFromSenderName(senderName: string | null | undefined): Promise<string | null> {
  return (await call<string | undefined>('orchestrationCreatorFromSenderName', senderName ?? null)) ?? null;
}
