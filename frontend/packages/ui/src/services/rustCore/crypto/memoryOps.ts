/**
 * Assistant Memory write ops of the crypto unit (`memory*` Worker exports,
 * packages/openmates-browser-bindings/src/browser_memory_writes.rs).
 *
 * The job state machine, Memory validation, settings encryption and Undo rules
 * run in the Rust core (memory_write_jobs.rs, memory_write_job_bridge.rs). A
 * frame call resolves either `done` (frames to send) or one IO effect that the
 * page performs and answers with `memoryJobResume`. Rejections carry the core's
 * stable codes (`rule_changed`, `rule_not_found`, ...).
 */
import type { WebCryptoOp } from './webCryptoClient';

export type MemoryOp = 'memoryJobFrame' | 'memoryJobResume' | 'memoryJobsClear' | 'memoryUndoPrepare';

/** Worker export behind each op; spread into the crypto unit's async export table. */
export const MEMORY_ASYNC_EXPORTS: Record<MemoryOp, string> = {
  memoryJobFrame: 'memoryJobFrame',
  memoryJobResume: 'memoryJobResume',
  memoryJobsClear: 'memoryJobsClear',
  memoryUndoPrepare: 'memoryUndoPrepare',
};

/** IO the page performs for the core (see MemoryJobEffect in the bridge). */
export type MemoryJobEffect =
  | { kind: 'post_settings'; encrypted_settings: string }
  | { kind: 'notice'; chat_id: string; user_message_id: string; message_id: string; content: string };

/** One step of a running job frame. */
export type MemoryJobStep =
  | { done: { frames: [string, Record<string, unknown>][] } }
  | { token: number; effect: MemoryJobEffect };

export interface MemoryUndoPrepared {
  outcome: 'deleted' | 'restored';
  encrypted_settings: string;
  /** Message id and content of the persisted undone marker. */
  marker_id: string;
  marker: string;
}

/** The slice of WebCryptoClient these helpers need (so tests can pass a fake). */
export interface MemoryOpsClient {
  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T>;
}

/** Starts one inbound `memory_write_job_*` frame in the core. */
export async function memoryJobFrame(
  client: MemoryOpsClient, masterKey: CryptoKey, settings: string | null, kind: string, event: unknown, nowSeconds: number,
): Promise<MemoryJobStep> {
  return JSON.parse(await client.call<string>('memoryJobFrame', masterKey, settings, kind, JSON.stringify(event), nowSeconds));
}

/** Answers the effect of `token` (`null` = success, else an error code). */
export async function memoryJobResume(client: MemoryOpsClient, token: number, outcome: string | null): Promise<MemoryJobStep> {
  return JSON.parse(await client.call<string>('memoryJobResume', token, outcome));
}

/** Encrypted settings and undone marker for Undo of an assistant write. */
export async function memoryUndoPrepare(
  client: MemoryOpsClient, masterKey: CryptoKey, settings: string | null, event: unknown, nowSeconds: number,
): Promise<MemoryUndoPrepared> {
  return JSON.parse(await client.call<string>('memoryUndoPrepare', masterKey, settings, JSON.stringify(event), nowSeconds));
}
