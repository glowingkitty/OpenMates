// Shared Rust core web crypto client (VITE_OPENMATES_RUST_CORE builds only).
// The web_app registers one client under the build flag; with the flag OFF
// nothing registers, the TS crypto modules never reach this code (their
// delegation is behind the same compile-time guard) and keep their original
// implementation. With the flag ON the TS modules are thin facades over the Rust
// formats running in the shared Rust core Worker's `crypto` unit
// (cryptoUnitInstaller.ts). No Rust/WASM runs on the page.
//
// Batching: calls issued in the same task are sent as one batch message. The
// flush waits while new calls keep arriving in the same microtask checkpoint
// (bounded hops), so a Promise.all over N decryptMessageFields-style callers
// with a few awaits each still costs one Worker round trip. Inside a batch,
// per-item calls that share an op and key (chat-content decrypt/encrypt,
// master-key unwrap) are coalesced into one `bulk` request: the key is cloned
// once and the Worker decrypts the whole list in one WASM call.
// CryptoKey objects are structured-cloned (extractable or not, they never expose
// raw bytes); raw chat keys the page already holds are copied, never transferred
// out of the caller's buffers.
// Repeated successful decrypts of the same ciphertext with the same key are
// answered from a bounded page-side memo (cryptoResultMemo.ts) without a Worker
// round trip; identical calls in flight share one request.
import { CryptoResultMemo, isBytes } from './cryptoResultMemo';
import type { KeyOp } from './keyOps';
import type { GuestOp } from './guestOps';

export type WebCryptoOp =
  | 'decryptChatContent' | 'encryptChatContent' | 'masterDecrypt' | 'masterEncrypt'
  | 'generateShareKeyBlob' | 'decryptShareKeyBlob' | 'encryptShareUrl' | 'decryptShareUrl'
  | 'decryptMedia' | 'guardBegin' | 'guardAfterAnonymous' | 'guardAfterPersisted' | 'clearChatKeys' | 'chatKeyCacheSize'
  // Benchmark attribution only (E2E proof harness): `echo` answers its argument
  // unchanged; `profileChatDecrypt` answers per-stage timings, never key bytes.
  | 'echo' | 'profileChatDecrypt'
  | KeyOp
  | GuestOp
  | 'bulk';

/** Per-item ops the flush coalesces: `[key, item]` args, one `bulk` request per key. */
export type WebCryptoBulkOp = 'decryptChatContent' | 'encryptChatContent' | 'masterDecrypt';
export const WEB_CRYPTO_BULK_OPS: ReadonlySet<string> = new Set<WebCryptoBulkOp>(['decryptChatContent', 'encryptChatContent', 'masterDecrypt']);
/**
 * `bulk` args: `[op, key, items]`. Its value holds one entry per item, in
 * order; items listed in `errors` (`[index, code]`) reject with that code.
 */
export interface WebCryptoBulkResult { values: unknown[]; errors: [number, string][] }
/** Items per `bulk` request: the unit answers each request on its own, so the page settles early chunks while later ones run. */
export const WEB_CRYPTO_BULK_CHUNK = 256;

export interface WebCryptoRequest { id: number; op: WebCryptoOp; args: unknown[] }
export type WebCryptoResponse =
  | { id: number; ok: true; value: unknown }
  | { id: number; ok: false; error: string };
export interface WebCryptoBatch { version: 1; requests: WebCryptoRequest[] }
export interface WebCryptoReplies { version: 1; responses: WebCryptoResponse[] }

/**
 * Page end of the crypto unit. `send` may be called before the port is open
 * (the endpoint buffers); `onReplies` receives every reply batch; `onFailure`
 * fires once when the unit can no longer answer (open refused, Worker crash).
 */
export interface WebCryptoEndpoint {
  send(batch: WebCryptoBatch): void;
  onReplies(listener: (replies: WebCryptoReplies) => void): void;
  onFailure(listener: (error: Error) => void): void;
  close(): void;
}
export type WebCryptoEndpointFactory = () => WebCryptoEndpoint;

export type ChatContentResult = string | null | { fingerprintMismatch: string };
export interface ShareKeyResult {
  success: boolean;
  chatEncryptionKey?: string;
  embedKey?: Uint8Array;
  error?: 'expired' | 'password_required' | 'invalid_password' | 'decryption_failed';
}

export interface WebCryptoStats {
  calls: Record<string, number>;
  failures: Record<string, number>;
  fingerprintMismatches: number;
  workerErrors: number;
  /** Batch messages posted to the Worker and the requests they carried. */
  batches: number;
  batchedRequests: number;
  /** Worker `bulk` requests and the per-item calls they carried. */
  bulkRequests: number;
  bulkItems: number;
  /** clearChatKeys() runs (logout / account switch / key removal via clearCryptoKeyCache). */
  chatKeyClears: number;
  /** Calls answered from the decrypt memo, and calls that joined an identical in-flight request. */
  memoHits: number;
  memoShared: number;
}

/** Microtask hops the flush always yields, and at most waits while the queue keeps growing. */
const MIN_FLUSH_HOPS = 4;
const MAX_FLUSH_HOPS = 32;

export class WebCryptoClient {
  private nextId = 1;
  private queue: WebCryptoRequest[] = [];
  private pending = new Map<number, { resolve(value: unknown): void; reject(error: Error): void }>();
  private bulkMembers = new Map<number, number[]>();
  private endpoint: WebCryptoEndpoint | null = null;
  private broken: Error | null = null;
  private flushScheduled = false;
  private readonly memo = new CryptoResultMemo();
  readonly stats: WebCryptoStats = {
    calls: {}, failures: {}, fingerprintMismatches: 0, workerErrors: 0,
    batches: 0, batchedRequests: 0, bulkRequests: 0, bulkItems: 0, chatKeyClears: 0,
    memoHits: 0, memoShared: 0,
  };

  constructor(private readonly factory: WebCryptoEndpointFactory) {}

  private start(): WebCryptoEndpoint {
    if (this.endpoint) return this.endpoint;
    const endpoint = this.factory();
    endpoint.onReplies((replies) => this.receive(replies));
    endpoint.onFailure((error) => {
      if (this.endpoint !== endpoint) return;
      // In-flight calls reject; the next call opens a fresh unit (the shared
      // core supervisor respawns a crashed Worker). No TS fallback.
      this.endpoint = null;
      endpoint.close();
      this.fail(error);
    });
    this.endpoint = endpoint;
    return endpoint;
  }

  private receive(replies: WebCryptoReplies): void {
    if (replies?.version !== 1 || !Array.isArray(replies.responses)) return;
    for (const response of replies.responses) {
      const members = this.bulkMembers.get(response.id);
      if (members) {
        this.bulkMembers.delete(response.id);
        const bulk = response.ok ? (response.value as WebCryptoBulkResult | null) : null;
        if (!response.ok || !Array.isArray(bulk?.values) || bulk.values.length !== members.length || !Array.isArray(bulk.errors)) {
          const error = 'error' in response ? response.error : 'rust_web_crypto_bulk_malformed';
          for (const memberId of members) this.settle(memberId, { ok: false, error });
          continue;
        }
        const errors = new Map(bulk.errors);
        members.forEach((memberId, index) => {
          const error = errors.get(index);
          this.settle(memberId, error === undefined ? { ok: true, value: bulk.values[index] } : { ok: false, error });
        });
        continue;
      }
      this.settle(response.id, response);
    }
  }

  private settle(id: number, response: { ok: true; value: unknown } | { ok: false; error: string }): void {
    const waiter = this.pending.get(id);
    if (!waiter) return;
    this.pending.delete(id);
    if ('error' in response) waiter.reject(new Error(response.error));
    else waiter.resolve(response.value);
  }

  private fail(error: Error): void {
    this.stats.workerErrors += 1;
    console.error('[RustWebCrypto] Crypto unit failed; its pending Rust crypto calls reject', error);
    for (const waiter of this.pending.values()) waiter.reject(error);
    this.pending.clear();
    this.bulkMembers.clear();
    this.queue = [];
  }

  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T> {
    this.stats.calls[op] = (this.stats.calls[op] ?? 0) + 1;
    if (this.broken) {
      this.recordFailure(op);
      return Promise.reject(this.broken);
    }
    const slot = this.memo.slotOf(op, args);
    if (slot === null) return this.request<T>(op, args);
    const hit = this.memo.get(slot);
    if (hit !== undefined) {
      this.stats.memoHits += 1;
      return Promise.resolve(hit as T);
    }
    const pending = this.memo.pending(slot);
    if (pending) {
      this.stats.memoShared += 1;
      // Each sharer gets its own copy of byte results (callers may zeroize theirs).
      return pending.then((value) => (isBytes(value) ? new Uint8Array(value) : value) as T);
    }
    const request = this.request<T>(op, args);
    this.memo.track(slot, request);
    return request;
  }

  private request<T>(op: WebCryptoOp, args: unknown[]): Promise<T> {
    const id = this.nextId++;
    const result = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
    });
    this.queue.push({ id, op, args });
    this.scheduleFlush();
    return result.catch((error: Error) => {
      this.recordFailure(op);
      throw error;
    });
  }

  private scheduleFlush(): void {
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    let seen = this.queue.length;
    let hops = 0;
    const step = () => {
      // Always yield a few hops (callers a few awaits deep join), then keep
      // waiting only while the queue still grows.
      if ((hops < MIN_FLUSH_HOPS || this.queue.length > seen) && hops < MAX_FLUSH_HOPS) {
        seen = this.queue.length;
        hops += 1;
        queueMicrotask(step);
        return;
      }
      this.flushScheduled = false;
      this.flush();
    };
    queueMicrotask(step);
  }

  private flush(): void {
    const requests = this.coalesce(this.queue);
    this.queue = [];
    if (requests.length === 0) return;
    this.stats.batches += 1;
    this.stats.batchedRequests += requests.length;
    this.start().send({ version: 1, requests });
  }

  /**
   * Groups same-op, same-key per-item requests into one `bulk` request each
   * (CryptoKeys by identity, raw chat keys by bytes); order within a group and
   * every other request is preserved. Groups of one are sent unchanged; larger
   * groups are split into requests of at most WEB_CRYPTO_BULK_CHUNK items.
   */
  private coalesce(requests: WebCryptoRequest[]): WebCryptoRequest[] {
    const groups: { op: WebCryptoOp; key: unknown; members: WebCryptoRequest[] }[] = [];
    const out: (WebCryptoRequest | (typeof groups)[number])[] = [];
    for (const request of requests) {
      if (!WEB_CRYPTO_BULK_OPS.has(request.op) || request.args.length !== 2) {
        out.push(request);
        continue;
      }
      const key = request.args[0];
      let group = groups.find((candidate) => candidate.op === request.op && candidate.members.length < WEB_CRYPTO_BULK_CHUNK
        && sameKey(candidate.key, key));
      if (!group) {
        group = { op: request.op, key, members: [] };
        groups.push(group);
        out.push(group);
      }
      group.members.push(request);
    }
    return out.map((entry) => {
      if (!('members' in entry)) return entry;
      if (entry.members.length === 1) return entry.members[0];
      const id = this.nextId++;
      this.bulkMembers.set(id, entry.members.map((member) => member.id));
      this.stats.bulkRequests += 1;
      this.stats.bulkItems += entry.members.length;
      return { id, op: 'bulk' as const, args: [entry.op, entry.key, entry.members.map((member) => member.args[1])] };
    });
  }

  /** Benchmark only: forgets memoized decrypt results so the next calls take the batched Worker path. */
  dropResultMemo(): void {
    this.memo.clear();
  }

  /**
   * Drops every cached chat-key cipher in the crypto unit. A unit that never
   * started holds none and is not started for this.
   */
  clearChatKeys(): Promise<void> {
    this.stats.chatKeyClears += 1;
    this.memo.clear();
    if (!this.endpoint && this.queue.length === 0) return Promise.resolve();
    return this.call<void>('clearChatKeys');
  }

  /** Cached chat-key ciphers in the crypto unit (logout proof; no key material). */
  async chatKeyCacheSize(): Promise<number> {
    return this.endpoint ? this.call<number>('chatKeyCacheSize') : 0;
  }

  recordFailure(op: WebCryptoOp): void {
    this.stats.failures[op] = (this.stats.failures[op] ?? 0) + 1;
  }

  close(): void {
    const endpoint = this.endpoint;
    this.endpoint = null;
    endpoint?.close();
    this.memo.clear();
    this.broken = new Error('rust_web_crypto_closed');
    for (const waiter of this.pending.values()) waiter.reject(this.broken);
    this.pending.clear();
    this.bulkMembers.clear();
    this.queue = [];
  }
}

function sameKey(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!(a instanceof Uint8Array) || !(b instanceof Uint8Array) || a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index += 1) diff |= a[index] ^ b[index];
  return diff === 0;
}

let client: WebCryptoClient | null = null;
let baselineDepth = 0;

/** Registers the crypto unit client (web_app, flag ON only). */
export function registerRustWebCrypto(factory: WebCryptoEndpointFactory): WebCryptoClient {
  client?.close();
  client = new WebCryptoClient(factory);
  return client;
}

/**
 * Clears the crypto unit's cached chat-key ciphers when the flag build
 * registered a client; a no-op otherwise. Called by
 * MessageEncryptor.clearCryptoKeyCache, which ChatKeyManager runs on logout,
 * account switch, cross-tab clear and key removal. Failures are logged.
 */
export function clearRustChatKeyCaches(): void {
  client?.clearChatKeys().catch((error: unknown) =>
    console.error('[RustWebCrypto] Failed to clear crypto unit chat-key ciphers', error),
  );
}

/** The Rust facade client, or null when nothing registered (TS implementation runs). */
export function rustWebCrypto(): WebCryptoClient | null {
  return baselineDepth > 0 ? null : client;
}

/**
 * Benchmark only: run `operation` against the original TypeScript implementation
 * in the same page. Never used by application code.
 */
export async function runTypeScriptCryptoBaseline<T>(operation: () => Promise<T>): Promise<T> {
  baselineDepth += 1;
  try {
    return await operation();
  } finally {
    baselineDepth -= 1;
  }
}
