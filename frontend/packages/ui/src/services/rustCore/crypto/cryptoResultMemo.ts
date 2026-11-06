// Page-side memo of deterministic Rust crypto-unit decrypt results
// (VITE_OPENMATES_RUST_CORE builds only; used by webCryptoClient.ts).
//
// After a reload the TS sync, chat list, draft and guard code decrypt the same
// chat titles and master-key-wrapped chat keys many times, mostly one awaited call
// at a time. With TS crypto each repeat is one WebCrypto call; with the crypto
// unit each repeat is a page<->Worker round trip that the batcher cannot coalesce
// (it was awaited alone), so on the send path those repeats cost wall time and CPU
// on both threads. AES-GCM decryption is deterministic for a given key and
// ciphertext, so a successful result is reused instead of asking the Worker again,
// and identical calls already in flight share one request.
//
// Only successful results are kept (a failure, a fingerprint mismatch or a null
// decrypt always goes to the Worker again, so the caller's recovery paths run
// unchanged). Keys are matched by identity (master CryptoKey) or by exact bytes
// (raw chat keys, compared in full). Byte results are copied on every hit so a
// caller zeroizing its buffer never changes the cache. Bounded by entry count and
// bytes; `clear()` zeroizes and drops everything (logout, account switch, chat-key
// cache clear, client close).

/** Ops whose `[key, ciphertext]` result is memoized. */
export type MemoOp = 'decryptChatContent' | 'masterDecrypt';
const MEMO_OPS: ReadonlySet<string> = new Set<MemoOp>(['decryptChatContent', 'masterDecrypt']);

const MAX_ENTRIES = 4096;
/** Distinct raw chat keys remembered; beyond this the memo starts over. */
const MAX_RAW_KEYS = 4096;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;
/** Larger results (media-sized payloads) are never kept. */
const MAX_VALUE_BYTES = 64 * 1024;

type Value = string | Uint8Array;
interface RawKeySlot { bytes: Uint8Array; id: number }

/** Uint8Array check that also holds across realms (structured clones, test environments). */
export function isBytes(value: unknown): value is Uint8Array {
  return ArrayBuffer.isView(value) && Object.prototype.toString.call(value) === '[object Uint8Array]';
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index += 1) diff |= a[index] ^ b[index];
  return diff === 0;
}

/** Non-cryptographic bucket index for raw keys; every hit is confirmed by a full byte compare. */
function bucketOf(bytes: Uint8Array): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < bytes.length; index += 1) hash = Math.imul(hash ^ bytes[index], 0x01000193);
  return hash >>> 0;
}

function sizeOf(value: Value): number {
  return typeof value === 'string' ? value.length * 2 : value.byteLength;
}

export class CryptoResultMemo {
  private nextKeyId = 1;
  private cryptoKeyIds = new WeakMap<CryptoKey, number>();
  private rawKeySlots = new Map<number, RawKeySlot[]>();
  private rawKeyCount = 0;
  /** Insertion order is recency order (a hit re-inserts). */
  private values = new Map<string, Value>();
  private totalBytes = 0;
  private inFlight = new Map<string, Promise<unknown>>();

  /** Memo slot of a call, or null when the op/args are not memoizable. */
  slotOf(op: string, args: unknown[]): string | null {
    if (!MEMO_OPS.has(op) || args.length !== 2 || typeof args[1] !== 'string') return null;
    const key = args[0];
    let id: number | undefined;
    if (typeof CryptoKey !== 'undefined' && key instanceof CryptoKey) {
      id = this.cryptoKeyIds.get(key);
      if (id === undefined) {
        id = this.nextKeyId++;
        this.cryptoKeyIds.set(key, id);
      }
    } else if (isBytes(key)) {
      const bucket = bucketOf(key);
      const slots = this.rawKeySlots.get(bucket) ?? [];
      id = slots.find((slot) => sameBytes(slot.bytes, key))?.id;
      if (id === undefined) {
        if (this.rawKeyCount >= MAX_RAW_KEYS) {
          this.clear();
          return this.slotOf(op, args);
        }
        id = this.nextKeyId++;
        slots.push({ bytes: new Uint8Array(key), id });
        this.rawKeySlots.set(bucket, slots);
        this.rawKeyCount += 1;
      }
    } else {
      return null;
    }
    return `${op}\u0000${id}\u0000${args[1]}`;
  }

  /** A copy of the memoized result, or undefined. */
  get(slot: string): Value | undefined {
    const value = this.values.get(slot);
    if (value === undefined) return undefined;
    this.values.delete(slot);
    this.values.set(slot, value);
    return typeof value === 'string' ? value : new Uint8Array(value);
  }

  /** The in-flight request for the same slot, if any (callers share it). */
  pending(slot: string): Promise<unknown> | undefined {
    return this.inFlight.get(slot);
  }

  /** Tracks `request` as in flight for `slot` and keeps its successful result. */
  track(slot: string, request: Promise<unknown>): void {
    this.inFlight.set(slot, request);
    const done = () => {
      if (this.inFlight.get(slot) === request) this.inFlight.delete(slot);
    };
    request.then((value) => {
      // A clear() while in flight dropped the slot; its result is not kept.
      if (this.inFlight.get(slot) !== request) return;
      done();
      if (typeof value === 'string' || isBytes(value)) this.put(slot, value);
    }, done);
  }

  private put(slot: string, value: Value): void {
    const size = sizeOf(value);
    if (size > MAX_VALUE_BYTES) return;
    const stored = typeof value === 'string' ? value : new Uint8Array(value);
    const previous = this.values.get(slot);
    if (previous !== undefined) this.drop(slot, previous);
    this.values.set(slot, stored);
    this.totalBytes += size;
    while (this.values.size > MAX_ENTRIES || this.totalBytes > MAX_TOTAL_BYTES) {
      const [oldest, oldValue] = this.values.entries().next().value as [string, Value];
      this.drop(oldest, oldValue);
    }
  }

  private drop(slot: string, value: Value): void {
    this.values.delete(slot);
    this.totalBytes -= sizeOf(value);
    if (typeof value !== 'string') value.fill(0);
  }

  get size(): number {
    return this.values.size;
  }

  /** Zeroizes and drops every result and raw-key copy; in-flight results are not kept. */
  clear(): void {
    for (const value of this.values.values()) if (typeof value !== 'string') value.fill(0);
    this.values.clear();
    this.totalBytes = 0;
    for (const slots of this.rawKeySlots.values()) for (const slot of slots) slot.bytes.fill(0);
    this.rawKeySlots.clear();
    this.rawKeyCount = 0;
    this.cryptoKeyIds = new WeakMap();
    this.inFlight.clear();
  }
}
