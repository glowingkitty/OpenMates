/** Fixed existing-store IO only. Rust owns encrypted record/map/CAS policy.
 * Inactive until the actual original native pending/owning-port route is bound.
 * No DTO, digest, request success or transactionCommitted flag is a receipt.
 */
import { assertRustChatIORootFactory, isNativeChatIOEvent, type RustChatIORoot } from './browserAdapters';
export const RECOVERY_CHECKPOINT_KEY = 'openmates_rust_pending_recovery_v1';
export const RECOVERY_CHECKPOINT_MAX_BYTES = 32 * 1024 * 1024;
export type RecoveryCheckpointEffect =
  | { readonly version: 1; readonly operation: 'read'; readonly operationId: string; readonly owner: string }
  | { readonly version: 1; readonly operation: 'compare_and_put'; readonly operationId: string; readonly owner: string;
      readonly expected: string | null; readonly next: string };
declare const nativeRecoveryReadback: unique symbol;
export interface NativeRecoveryCheckpointReadback { readonly [nativeRecoveryReadback]: true }
export interface BrowserRecoveryCheckpointStorage {
  execute(effect: RecoveryCheckpointEffect, signal: AbortSignal): Promise<NativeRecoveryCheckpointReadback>;
  consume(readback: NativeRecoveryCheckpointReadback, effect: RecoveryCheckpointEffect): string | null;
  close(): Promise<void>;
}
function validRecord(value: unknown): value is string {
  return typeof value === 'string' && value.length <= RECOVERY_CHECKPOINT_MAX_BYTES
    && new TextEncoder().encode(value).byteLength <= RECOVERY_CHECKPOINT_MAX_BYTES;
}
/** Closed own-data framing only. This does not validate ciphertext or a job. */
function capture(effect: unknown): RecoveryCheckpointEffect {
  if (!effect || typeof effect !== 'object' || Object.getPrototypeOf(effect) !== Object.prototype) throw Error('unavailable');
  const descriptors = Object.getOwnPropertyDescriptors(effect), keys = Reflect.ownKeys(effect);
  if (keys.some(key => typeof key !== 'string' || !descriptors[key] || !('value' in descriptors[key]) || !descriptors[key].enumerable)) throw Error('unavailable');
  const value = Object.fromEntries(keys.map(key => [key, descriptors[key as string].value])) as Record<string, unknown>;
  const expected = value.operation === 'read' ? ['version', 'operation', 'operationId', 'owner']
    : ['version', 'operation', 'operationId', 'owner', 'expected', 'next'];
  const uuid = (input: unknown) => typeof input === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(input);
  if (keys.length !== expected.length || !keys.every(key => expected.includes(key as string))
    || value.version !== 1 || !uuid(value.operationId) || !uuid(value.owner)) throw Error('unavailable');
  if (value.operation === 'read') return Object.freeze({ version: 1, operation: 'read', operationId: value.operationId as string, owner: value.owner as string });
  if (value.operation !== 'compare_and_put' || !(value.expected === null || validRecord(value.expected)) || !validRecord(value.next)) throw Error('unavailable');
  return Object.freeze({ version: 1, operation: 'compare_and_put', operationId: value.operationId as string,
    owner: value.owner as string, expected: value.expected as string | null, next: value.next });
}
function sameEffect(a: RecoveryCheckpointEffect, b: RecoveryCheckpointEffect): boolean {
  return a.version === b.version && a.operation === b.operation && a.operationId === b.operationId && a.owner === b.owner
    && (a.operation === 'read' || (b.operation === 'compare_and_put' && a.expected === b.expected && a.next === b.next));
}
/** Capture native methods/getters once, before caller callbacks. A shadowed
 * request.result, transaction method or callback property cannot invent IO.
 */
function nativeMethods() {
  if (typeof IDBFactory === 'undefined' || typeof IDBRequest === 'undefined' || typeof IDBDatabase === 'undefined'
    || typeof IDBTransaction === 'undefined' || typeof IDBObjectStore === 'undefined' || typeof AbortSignal === 'undefined') return null;
  const get = (prototype: object, name: string) => Object.getOwnPropertyDescriptor(prototype, name)!.get!;
  const result = get(IDBRequest.prototype, 'result'), transaction = get(IDBRequest.prototype, 'transaction');
  const name = get(IDBDatabase.prototype, 'name'), stores = get(IDBDatabase.prototype, 'objectStoreNames');
  const keyPath = get(IDBObjectStore.prototype, 'keyPath'), eventType = get(Event.prototype, 'type');
  const aborted = get(AbortSignal.prototype, 'aborted');
  const open = IDBFactory.prototype.open, close = IDBDatabase.prototype.close, begin = IDBDatabase.prototype.transaction;
  const objectStore = IDBTransaction.prototype.objectStore, abort = IDBTransaction.prototype.abort;
  const read = IDBObjectStore.prototype.get, exists = IDBObjectStore.prototype.getKey, put = IDBObjectStore.prototype.put;
  const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
  return {
    open: (factory: IDBFactory) => open.call(factory, 'user_db'),
    aborted: (signal: AbortSignal) => aborted.call(signal) as boolean,
    result: (request: IDBRequest) => result.call(request) as unknown,
    upgrade: (request: IDBRequest) => transaction.call(request) as IDBTransaction | null,
    name: (database: IDBDatabase) => name.call(database) as string,
    stores: (database: IDBDatabase) => stores.call(database) as DOMStringList,
    close: (database: IDBDatabase) => close.call(database),
    begin: (database: IDBDatabase, mode: IDBTransactionMode) => begin.call(database, ['user_data'], mode),
    store: (tx: IDBTransaction) => objectStore.call(tx, 'user_data'),
    keyPath: (store: IDBObjectStore) => keyPath.call(store) as string | string[] | null,
    read: (store: IDBObjectStore, key: string) => read.call(store, key),
    exists: (store: IDBObjectStore, key: string) => exists.call(store, key),
    put: (store: IDBObjectStore, value: string) => put.call(store, value, RECOVERY_CHECKPOINT_KEY),
    abort: (tx: IDBTransaction) => abort.call(tx),
    listen: (target: EventTarget, kind: string, listener: EventListener) => {
      add.call(target, kind, listener);
      return () => remove.call(target, kind, listener);
    },
    trusted: (event: Event, target: EventTarget, kind: string) => isNativeChatIOEvent(event, target) && eventType.call(event) === kind,
  };
}
const native = nativeMethods();
export function createBrowserRecoveryCheckpointStorage(input: {
  factory: IDBFactory; root: RustChatIORoot; current: () => void;
}): BrowserRecoveryCheckpointStorage {
  if (!native) throw Error('unavailable');
  const io = native, factory = input.factory, root = input.root, current = input.current;
  let active = true, closing: Promise<void> | undefined;
  const pending = new Set<Promise<unknown>>(), aborters = new Set<() => void>();
  const readbacks = new WeakMap<object, { original: RecoveryCheckpointEffect; captured: RecoveryCheckpointEffect; record: string | null }>();
  const check = () => {
    if (!active) throw Error('unavailable');
    assertRustChatIORootFactory(root, factory); current(); assertRustChatIORootFactory(root, factory);
    if (!active) throw Error('unavailable');
  };
  check();
  const execute = (effect: RecoveryCheckpointEffect, signal: AbortSignal): Promise<NativeRecoveryCheckpointReadback> => {
    let captured: RecoveryCheckpointEffect;
    try { captured = capture(effect); check(); if (io.aborted(signal)) throw Error('cancelled'); }
    catch { let cancelled = false; try { cancelled = io.aborted(signal); } catch { /* Invalid native signal. */ } return Promise.reject(Error(cancelled ? 'cancelled' : 'unavailable')); }
    const operation = new Promise<NativeRecoveryCheckpointReadback>((resolve, reject) => {
      let open: IDBOpenDBRequest | null = null, database: IDBDatabase | null = null, tx: IDBTransaction | null = null;
      let upgrade: IDBTransaction | null = null, upgradeEnded = false, openEnded = false;
      let failure: 'unavailable' | 'cancelled' | 'conflict' | null = null, settled = false, readbackDone = false;
      let record: string | null = null;
      const releases: Array<() => void> = [];
      const cleanup = () => {
        aborters.delete(abortOriginal);
        for (const release of releases) release();
        if (database) { try { io.close(database); } catch { /* Actual terminal has already been observed. */ } }
      };
      const failTerminal = () => { if (settled) return; settled = true; cleanup(); reject(Error(failure ?? 'unavailable')); };
      const fail = (code: 'unavailable' | 'cancelled' | 'conflict') => {
        failure ??= code;
        for (const original of [tx, upgrade]) if (original) { try { io.abort(original); } catch { /* Await genuine terminal, including a racing commit. */ } }
      };
      const abortOriginal = () => fail(io.aborted(signal) ? 'cancelled' : 'unavailable');
      const currentEffect = () => { check(); if (io.aborted(signal)) throw Error('cancelled'); if (failure) throw Error(failure); };
      const guarded = (fn: () => void) => { try { currentEffect(); fn(); } catch { fail(io.aborted(signal) ? 'cancelled' : 'unavailable'); } };
      const listen = (target: EventTarget, kind: string, fn: (event: Event) => void) => {
        releases.push(io.listen(target, kind, event => {
          if (!io.trusted(event, target, kind)) { fail('unavailable'); return; }
          fn(event);
        }));
      };
      const request = (value: IDBRequest, success: (result: unknown) => void) => {
        listen(value, 'success', () => guarded(() => success(io.result(value))));
        listen(value, 'error', () => fail('unavailable')); // NOT a transaction terminal.
      };
      const terminalOpenFailure = () => { if (openEnded && (!upgrade || upgradeEnded)) failTerminal(); };
      aborters.add(abortOriginal); releases.push(io.listen(signal, 'abort', abortOriginal));
      try {
        currentEffect(); open = io.open(factory);
        listen(open, 'upgradeneeded', () => {
          // Never create, upgrade, repair, or open a substitute database/store.
          try { database = io.result(open!) as IDBDatabase; upgrade = io.upgrade(open!); } catch { failure ??= 'unavailable'; }
          if (upgrade) {
            for (const kind of ['abort', 'complete']) listen(upgrade, kind, () => { upgradeEnded = true; terminalOpenFailure(); });
          }
          fail('unavailable');
        });
        listen(open, 'error', () => { openEnded = true; failure ??= 'unavailable'; terminalOpenFailure(); });
        listen(open, 'success', () => {
          openEnded = true;
          try {
            database = io.result(open!) as IDBDatabase;
            if (failure || !active || io.aborted(signal)) { failure ??= io.aborted(signal) ? 'cancelled' : 'unavailable'; failTerminal(); return; }
            currentEffect();
            if (io.name(database) !== 'user_db' || !io.stores(database).contains('user_data')) throw Error('unavailable');
            listen(database, 'versionchange', () => { fail('unavailable'); });
            tx = io.begin(database, captured.operation === 'read' ? 'readonly' : 'readwrite');
            // Install native terminal observers before exposing any store IO.
            listen(tx, 'abort', () => { failure ??= 'unavailable'; failTerminal(); });
            listen(tx, 'complete', () => {
              if (settled) return;
              if (failure || !readbackDone) { failure ??= 'unavailable'; failTerminal(); return; }
              try {
                currentEffect();
                const token = Object.freeze({ checkpoint: () => undefined }) as unknown as NativeRecoveryCheckpointReadback;
                readbacks.set(token, { original: effect, captured, record });
                settled = true; cleanup(); resolve(token);
              } catch { failure ??= io.aborted(signal) ? 'cancelled' : 'unavailable'; failTerminal(); }
            });
            listen(tx, 'error', () => { failure ??= 'unavailable'; }); // Never count bubbling error as drain.
            const store = io.store(tx);
            if (io.keyPath(store) !== null) { fail('unavailable'); return; }
            const accept = (previous: string | null) => {
              if (captured.operation === 'read') { record = previous; readbackDone = true; return; }
              if (previous !== captured.expected) { fail('conflict'); return; }
              request(io.put(store, captured.next), () => {
                // Full stored record, not put success or a caller-supplied hash.
                request(io.read(store, RECOVERY_CHECKPOINT_KEY), written => {
                  if (!validRecord(written) || written !== captured.next) { fail('conflict'); return; }
                  record = written; readbackDone = true;
                });
              });
            };
            request(io.read(store, 'id'), owner => {
              if (owner !== captured.owner) { fail('unavailable'); return; }
              request(io.exists(store, RECOVERY_CHECKPOINT_KEY), key => {
                if (key === undefined) { accept(null); return; }
                request(io.read(store, RECOVERY_CHECKPOINT_KEY), previous => {
                  if (!validRecord(previous)) { fail('unavailable'); return; }
                  accept(previous);
                });
              });
            });
          } catch { fail('unavailable'); if (!tx) failTerminal(); }
        });
        currentEffect();
      } catch {
        fail(io.aborted(signal) ? 'cancelled' : 'unavailable');
        if (!open) failTerminal(); // No native request/transaction was started.
      }
    });
    pending.add(operation); void operation.then(() => pending.delete(operation), () => pending.delete(operation));
    return operation;
  };
  return Object.freeze({
    execute,
    consume(readback: NativeRecoveryCheckpointReadback, effect: RecoveryCheckpointEffect): string | null {
      const value = readbacks.get(readback); readbacks.delete(readback);
      check();
      if (!value || value.original !== effect || !sameEffect(value.captured, capture(effect))) throw Error('unavailable');
      return value.record;
    },
    close(): Promise<void> {
      active = false; for (const abort of [...aborters]) abort();
      return closing ??= (async () => { while (pending.size) await Promise.allSettled([...pending]); })();
    },
  });
}
