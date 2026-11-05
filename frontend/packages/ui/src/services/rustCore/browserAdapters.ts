/** Thin browser primitives. Rust chooses auth, ownership and persistence policy. */
export const AUTH_REFRESH_LOCK = "openmates:auth-session-refresh";

declare const refreshLeaseBrand: unique symbol;
export interface AuthRefreshLease { readonly [refreshLeaseBrand]: true }
declare const effectLeaseBrand: unique symbol;
export interface AuthRefreshEffectLease { readonly [effectLeaseBrand]: true }

type LeaseState = { active: boolean; signal: AbortSignal; current: () => void;
  controller: AbortController; pending: Set<Promise<unknown>> };
type LockState = LeaseState & { locks: LockManager };
type EffectState = LeaseState & { issuer: object; operationId: string };
const lockLeases = new WeakMap<object, LockState>();
const effectLeases = new WeakMap<object, EffectState>();
function checkLease(state: LeaseState): void {
  if (!state.active || state.signal.aborted || state.controller.signal.aborted) throw new Error("invalidated_snapshot");
  state.current();
}
function opaqueLease(): object {
  // An own function makes structured clone fail; WeakMaps reject every copy.
  return Object.freeze({ checkpoint: () => undefined });
}
function runLeased<T>(state: LeaseState, operation: (signal: AbortSignal) => Promise<T>, checkResult = true): Promise<T> {
  checkLease(state);
  const pending = Promise.resolve().then(() => { checkLease(state); return operation(state.controller.signal); })
    .then(result => { if (checkResult) checkLease(state); return result; });
  state.pending.add(pending);
  void pending.then(() => state.pending.delete(pending), () => state.pending.delete(pending));
  return pending;
}
async function revokeLease(state: LeaseState): Promise<void> {
  state.active = false;
  state.controller.abort();
  // Aborting a caller does not attest IDB termination. Every registered effect
  // resolves/rejects only after its actual transaction terminal event.
  while (state.pending.size) await Promise.allSettled([...state.pending]);
}
function makeState(signal: AbortSignal, current: () => void): LeaseState {
  const state: LeaseState = { active: true, signal, current, controller: new AbortController(), pending: new Set() };
  checkLease(state);
  return state;
}

/** Existing WebLock, with local inherited ownership only; no auth policy. */
export async function withAuthRefreshLock<T>(locks: LockManager, signal: AbortSignal,
  operation: (lease: AuthRefreshLease) => Promise<T>,
  options: { lease?: AuthRefreshLease; current?: () => void } = {}): Promise<T> {
  const current = options.current ?? (() => undefined);
  if (signal.aborted) throw new Error("cancelled");
  current();
  const inherited = options.lease;
  if (inherited !== undefined) {
    const state = lockLeases.get(inherited);
    if (!state || state.locks !== locks) throw new Error("invalidated_snapshot");
    return runLeased(state, async () => {
      if (signal.aborted) throw new Error("cancelled");
      current();
      const result = await operation(inherited);
      if (signal.aborted) throw new Error("cancelled");
      current();
      return result;
    });
  }
  if (!locks || typeof locks.request !== "function") throw new Error("auth_refresh_lock_unavailable");
  return await locks.request(AUTH_REFRESH_LOCK, { mode: "exclusive", signal }, async () => {
    if (signal.aborted) throw new Error("cancelled");
    current();
    const state: LockState = { ...makeState(signal, current), locks };
    const lease = opaqueLease() as AuthRefreshLease;
    lockLeases.set(lease, state);
    const abort = () => state.controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    // Legacy callers receive their returned resource even after cancellation,
    // so their existing owner can dispose it. Stronger scoped callers opt into
    // a post-effect validity check; reverse IO leases always require that check.
    try { return await runLeased(state, () => operation(lease), options.current !== undefined); }
    finally { await revokeLease(state); signal.removeEventListener("abort", abort); lockLeases.delete(lease); }
  });
}

/** WorkerHost calls only after correlating a real reverse effect to its owned
 * endpoint/pending Rust CAS request. This token is local correlation, never
 * evidence that a remote Worker owns a WebLock or that Rust admitted an owner.
 */
export function openAuthRefreshEffectLease(issuer: object, operationId: string, signal: AbortSignal,
  current: () => void): { lease: AuthRefreshEffectLease; close: () => Promise<void> } {
  if (!issuer || typeof issuer !== "object" || typeof operationId !== "string" || operationId.length < 1 || operationId.length > 128)
    throw new Error("invalid_request");
  const state: EffectState = { ...makeState(signal, current), issuer, operationId };
  const lease = opaqueLease() as AuthRefreshEffectLease;
  effectLeases.set(lease, state);
  const abort = () => state.controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  let closing: Promise<void> | null = null;
  return { lease, close: () => {
    if (!closing) closing = revokeLease(state).finally(() => {
      signal.removeEventListener("abort", abort); effectLeases.delete(lease);
    });
    return closing;
  } };
}
export function assertAuthRefreshEffectLease(lease: AuthRefreshEffectLease, issuer: object, operationId: string): void {
  const state = effectLeases.get(lease);
  if (!state || state.issuer !== issuer || state.operationId !== operationId) throw new Error("invalidated_snapshot");
  checkLease(state);
}
/** The callback must await the real IO terminal event, including abort. */
export function withAuthRefreshEffectLease<T>(lease: AuthRefreshEffectLease, issuer: object, operationId: string,
  operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
  assertAuthRefreshEffectLease(lease, issuer, operationId);
  return runLeased(effectLeases.get(lease)!, operation);
}

/** Request success is NOT durability; resolve only on the owned transaction's completion. */
export function committedRequest<T>(transaction: IDBTransaction, request: IDBRequest<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    let result: T;
    let succeeded = false;
    const cleanup = () => signal.removeEventListener("abort", abort);
    const abort = () => { try { transaction.abort(); } catch { /* Already settled. */ } };
    transaction.oncomplete = () => {
      cleanup();
      if (succeeded && !signal.aborted) resolve(result);
      else reject(new Error(signal.aborted ? "cancelled" : "storage_failed"));
    };
    transaction.onabort = () => { cleanup(); reject(new Error(signal.aborted ? "cancelled" : "storage_failed")); };
    transaction.onerror = () => { /* The abort event owns failure settlement. */ };
    request.onsuccess = () => { result = request.result; succeeded = true; };
    request.onerror = () => { /* Never resolve before transaction completion. */ };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** No schema changes: legacy master_key remains the CryptoKey itself, not JSON. */
export function masterKeyRequest(db: IDBDatabase, mode: "read" | "write" | "delete", key: CryptoKey | null, signal: AbortSignal): Promise<unknown> {
  if (mode === "write" && key === null) return Promise.reject(new Error("invalid_request"));
  const transaction = db.transaction("keys", mode === "read" ? "readonly" : "readwrite");
  const store = transaction.objectStore("keys");
  const request = mode === "read" ? store.get("master_key")
    : mode === "delete" ? store.delete("master_key") : store.put(key, "master_key");
  return committedRequest(transaction, request, signal);
}

declare const chatWriteScopeBrand: unique symbol;
export interface LocalChatWriteScope { readonly [chatWriteScopeBrand]: true }
declare const chatWriteSnapshotBrand: unique symbol;
export interface LocalChatWriteSnapshot { readonly [chatWriteSnapshotBrand]: true }
export interface LocalChatWriteTerminal {
  readonly outcome: "complete" | "abort";
  readonly error: DOMException | null;
  readonly errorObserved: boolean;
}
type ChatWriteState = LeaseState & { database: IDBDatabase; transactions: Set<IDBTransaction> };
type ChatWriteRecord = {
  scope: LocalChatWriteScope | undefined;
  terminal: Promise<LocalChatWriteTerminal>;
  settled: boolean;
};
const chatWriteScopes = new WeakMap<object, ChatWriteState>();
const chatWriteRecords = new WeakMap<IDBTransaction, ChatWriteRecord>();
const pendingChatWrites = new WeakMap<IDBDatabase, Set<IDBTransaction>>();
const chatWriteSnapshots = new WeakMap<object, readonly IDBTransaction[]>();
const legacyChatFactories = new WeakMap<IDBDatabase, LegacyChatDatabaseGate>();

/** Opaque, local transport lineage. None of these tokens changes Rust auth,
 * account/key policy or proves complete legacy producer retirement. */
declare const nativeChatFactoryBrand: unique symbol;
export interface NativeRustChatIOFactory { readonly [nativeChatFactoryBrand]: true }
declare const nativeChatRootBrand: unique symbol;
export interface RustChatIORoot { readonly [nativeChatRootBrand]: true }
declare const nativeChatLeaseBrand: unique symbol;
export interface RustChatIORoutingLease { readonly [nativeChatLeaseBrand]: true }
declare const nativeChatDrainedBrand: unique symbol;
export interface RustChatIODrainedReceipt { readonly [nativeChatDrainedBrand]: true }
type NativeFactoryState = { worker: Worker; factory: IDBFactory; active:boolean; admission:MessageEvent<unknown>|null };
type NativeRootState = NativeFactoryState & { issuer: NativeRustChatIOFactory;
  active: boolean; current: () => void; closeAndDrain: () => Promise<void>;
  pending: Set<Promise<unknown>>; transactions: Set<IDBTransaction>;
  draining?: Promise<RustChatIODrainedReceipt>; negativeObservers: Set<() => void> };
type NativeLeaseState = { root: RustChatIORoot; state: NativeRootState; gate: LegacyChatDatabaseGate };
const nativeChatFactories = new WeakMap<object, NativeFactoryState>();
const nativeChatRoots = new WeakMap<object, NativeRootState>();
const nativeChatLeases = new WeakMap<object, NativeLeaseState>();
const nativeChatReceipts = new WeakMap<object, NativeRootState>();
const nativeChatRequests = new WeakMap<IDBOpenDBRequest, { lease: RustChatIORoutingLease; factory: IDBFactory;terminal:Promise<void> }>();
const nativeChatConnections = new WeakMap<IDBDatabase, NativeLeaseState>();
// Capture intrinsic native accessors once. Structural objects, Proxy wrappers,
// copied fields and inherited Event.prototype objects cannot pass the native
// Event brand. isTrusted is a non-configurable browser-owned Event property.
const nativeTarget = Object.getOwnPropertyDescriptor(Event.prototype, 'target')!.get!;
const nativeType = Object.getOwnPropertyDescriptor(Event.prototype, 'type')!.get!;
const nativeMessageData = Object.getOwnPropertyDescriptor(MessageEvent.prototype, 'data')!.get!;
function isTrustedTarget(event: Event, target: EventTarget): boolean {
  try { nativeType.call(event); return nativeTarget.call(event) === target && event.isTrusted === true; }
  catch { return false; }
}
export function isNativeChatIOEvent(event:Event,target:EventTarget):boolean{return isTrustedTarget(event,target);}
/** Native transport data only; no account, policy or resource grant. */
export function readNativeChatIOMessage(event:MessageEvent<unknown>,target:EventTarget):unknown{
  if(!isTrustedTarget(event,target))throw Error('invalidated_snapshot');
  try{if(nativeType.call(event)!=='message')throw Error('invalidated_snapshot');return nativeMessageData.call(event);}catch{throw Error('invalidated_snapshot');}
}
function trustedTarget(event: Event, target: EventTarget): void {
  if (!isTrustedTarget(event,target)) throw Error('invalidated_snapshot');
}
/** Actual production loader calls after validating its emitted Worker's native
 * bootstrap event. Copied wire status and synthetic dispatch cannot enroll. */
export function openNativeRustChatIOFactory(worker: Worker, factory: IDBFactory,
  nativeReadyEvent: MessageEvent<unknown>): NativeRustChatIOFactory {
  trustedTarget(nativeReadyEvent, worker);
  let ready:unknown;try{ready=nativeMessageData.call(nativeReadyEvent);}catch{throw Error('invalidated_snapshot');}
  if(nativeType.call(nativeReadyEvent)!=='message'||!ready||typeof ready!=='object'||Object.keys(ready).length!==2||!('version' in ready)||ready.version!==1||!('ready' in ready)||ready.ready!==true)throw Error('invalidated_snapshot');
  const issuer = opaqueLease() as NativeRustChatIOFactory;
  nativeChatFactories.set(issuer, { worker, factory, active:true, admission:null });
  return issuer;
}
/** Only the Host's validated pending restore_existing native receive path is
 * retained for this call. Original witness/key checks remain with its session. */
export function enrollNativeRustChatIORoot(input: { issuer: NativeRustChatIOFactory;
  worker: Worker; factory: IDBFactory; current: () => void; closeAndDrain: () => Promise<void> },
  nativeRestoreEvent: MessageEvent<unknown>): RustChatIORoot {
  const source = nativeChatFactories.get(input.issuer);
  if (!source || !source.active || source.admission!==nativeRestoreEvent || source.worker !== input.worker || source.factory !== input.factory) throw Error('invalidated_snapshot');
  trustedTarget(nativeRestoreEvent, input.worker); input.current();
  const root = opaqueLease() as RustChatIORoot;
  nativeChatRoots.set(root, { ...source, issuer: input.issuer, current: input.current,
    closeAndDrain: input.closeAndDrain, active: true, pending: new Set(), transactions: new Set(), negativeObservers:new Set() });
  return root;
}
/** Host calls only after validating the exact original pending restore reply.
 * Native readiness, a copied status and other message kinds cannot enroll. */
export function recordNativeRustChatRestoreAdmission(issuer:NativeRustChatIOFactory,worker:Worker,
 event:MessageEvent<unknown>,originalPendingId:number):void{
 const source=nativeChatFactories.get(issuer);if(!source||!source.active||source.worker!==worker)throw Error('invalidated_snapshot');
 trustedTarget(event,worker);
 let reply:unknown;try{reply=nativeMessageData.call(event);}catch{throw Error('invalidated_snapshot');}
 if(nativeType.call(event)!=='message'||!reply||typeof reply!=='object'||!('id' in reply)||reply.id!==originalPendingId
  ||!('version' in reply)||reply.version!==1||!('ok' in reply)||reply.ok!==true||!('status' in reply)||!reply.status)throw Error('invalidated_snapshot');
 source.admission=event;
}
export function revokeNativeRustChatIOFactory(issuer:NativeRustChatIOFactory,worker:Worker):void{
 const source=nativeChatFactories.get(issuer);if(!source||source.worker!==worker)throw Error('invalidated_snapshot');
 source.active=false;source.admission=null;
}
export function assertNativeRustChatIOFactory(issuer: NativeRustChatIOFactory, worker: Worker, factory: IDBFactory): void {
  const state = nativeChatFactories.get(issuer);
  if (!state || !state.active || state.worker !== worker || state.factory !== factory) throw Error('invalidated_snapshot');
}
/** Resource-negative only: never invokes a caller/current callback or grants policy. */
export function assertRustChatIORootResource(root:RustChatIORoot):void{
  const state=nativeChatRoots.get(root);
  if(!state||!state.active)throw Error('invalidated_snapshot');
  const issuer=nativeChatFactories.get(state.issuer);
  if(!issuer?.active||issuer.admission!==state.admission)throw Error('invalidated_snapshot');
}
function currentRustChatRoot(root: RustChatIORoot): NativeRootState {
  assertRustChatIORootResource(root);
  const state=nativeChatRoots.get(root)!;
  state.current(); return state;
}
export function assertRustChatIORootCurrent(root: RustChatIORoot): void { currentRustChatRoot(root); }
/** Fixed native IO factory identity only. The original root witness callback
 * may synchronously revoke resources; recheck its negatives after the callback.
 * This does not admit an owner, choose policy, or project mutable status JSON. */
export function assertRustChatIORootFactory(root:RustChatIORoot,factory:IDBFactory):void{
  assertRustChatIORootResource(root);
  const state=nativeChatRoots.get(root)!;
  if(state.factory!==factory)throw Error('invalidated_snapshot');
  state.current();
  assertRustChatIORootResource(root);
  if(nativeChatRoots.get(root)!==state||state.factory!==factory)throw Error('invalidated_snapshot');
}
/** Exact originally admitted issuer/Worker/factory association, negative only.
 * Separate valid resources cannot be combined into a new IO routing authority. */
export function assertNativeRustChatIORootBinding(root:RustChatIORoot,issuer:NativeRustChatIOFactory,worker:Worker,factory:IDBFactory):void{
  assertRustChatIORootResource(root);
  const state=nativeChatRoots.get(root)!;
  if(state.issuer!==issuer||state.worker!==worker||state.factory!==factory)throw Error('invalidated_snapshot');
  assertNativeRustChatIOFactory(issuer,worker,factory);
  assertRustChatIORootFactory(root,factory);
  assertNativeRustChatIOFactory(issuer,worker,factory);
  assertRustChatIORootResource(root);
}
/** Negative-only subscription to this exact opaque original Root. No readiness,
 * settlement, native drain or admission follows from receiving notification. */
export function observeRustChatIORootInvalidation(root:RustChatIORoot,notify:()=>void):()=>void {
  const state=nativeChatRoots.get(root);if(!state)throw Error('invalidated_snapshot');
  if(!state.active){notify();return()=>{};}
  state.negativeObservers.add(notify);return()=>{state.negativeObservers.delete(notify);};
}
export function revokeRustChatIORoot(root: RustChatIORoot): void {
  const state = nativeChatRoots.get(root);
  if (!state) throw Error('invalidated_snapshot');
  if (!state.active) return;
  state.active = false;
  const observers=[...state.negativeObservers];state.negativeObservers.clear();
  for(const notify of observers)try{notify();}catch{/* Every original negative observer must run. */}
  for (const tx of state.transactions) { try { tx.abort(); } catch { /* Native terminal still required. */ } }
}
/** Host.close calls revoke ONLY. This outer path awaits Host IO + native IO;
 * its opaque receipt cannot attest native server inference/turn settlement. */
export function revokeAndDrainRustChatIORoot(root: RustChatIORoot): Promise<RustChatIODrainedReceipt> {
  const state = nativeChatRoots.get(root);
  if (!state) return Promise.reject(Error('invalidated_snapshot'));
  revokeRustChatIORoot(root);
  return state.draining ??= (async () => {
    await state.closeAndDrain();
    while (state.pending.size) await Promise.all([...state.pending]);
    const receipt = opaqueLease() as RustChatIODrainedReceipt;
    nativeChatReceipts.set(receipt, state); return receipt;
  })();
}
export function openRustChatIORoutingLease(root: RustChatIORoot, gate: LegacyChatDatabaseGate): RustChatIORoutingLease {
  const state = currentRustChatRoot(root);
  gate.attachRustRoot(root);
  const lease = opaqueLease() as RustChatIORoutingLease;
  nativeChatLeases.set(lease, { root, state, gate }); return lease;
}
function currentRustChatLease(lease: RustChatIORoutingLease, factory?: IDBFactory): NativeLeaseState {
  const owned = nativeChatLeases.get(lease);
  if (!owned || factory !== undefined && owned.state.factory !== factory) throw Error('invalidated_snapshot');
  if (currentRustChatRoot(owned.root) !== owned.state) throw Error('invalidated_snapshot');
  return owned;
}
/** Creates the original request through the exact admitted factory. An arbitrary
 * caller's native request cannot gain connection provenance after the fact. */
export function createRustChatOpenRequest(lease: RustChatIORoutingLease, factory: IDBFactory): IDBOpenDBRequest {
  const owned = currentRustChatLease(lease, factory);
  const request = factory.open('chats_db');
  let settle!: () => void;
  const terminal = new Promise<void>(resolve => { settle = resolve; });
  nativeChatRequests.set(request,{lease,factory,terminal});
  owned.state.pending.add(terminal);
  const finish = (event: Event) => {
    if (!isTrustedTarget(event, request)) return;
    if (event.type === 'success') {
      if (owned.state.active) {
        try { registerRustChatConnection(lease, factory, request, event); }
        catch { revokeRustChatIORoot(owned.root); request.result.close(); }
      } else request.result.close();
    }
    request.removeEventListener('success', finish); request.removeEventListener('error', finish);
    owned.state.pending.delete(terminal); settle();
  };
  request.addEventListener('success', finish); request.addEventListener('error', finish);
  request.addEventListener('upgradeneeded', event => {
    if (!isTrustedTarget(event, request)) return;
    revokeRustChatIORoot(owned.root);
    try { request.transaction?.abort(); } catch { /* Native open terminal is still required. */ }
  });
  return request;
}
export function registerRustChatConnection(lease: RustChatIORoutingLease, factory: IDBFactory,
  request: IDBOpenDBRequest, nativeOpenEvent: Event): void {
  const owned = currentRustChatLease(lease, factory), original = nativeChatRequests.get(request);
  if (!original || original.lease !== lease || original.factory !== factory) throw Error('invalidated_snapshot');
  trustedTarget(nativeOpenEvent, request);
  if (nativeOpenEvent.type !== 'success' || request.result.name !== 'chats_db') throw Error('invalidated_snapshot');
  owned.gate.assertConnectionVersion(request.result);
  nativeChatConnections.set(request.result, owned);
  const negative=(event:Event)=>{if(isTrustedTarget(event,request.result))revokeRustChatIORoot(owned.root);};
  request.result.addEventListener('versionchange',negative);
  request.result.addEventListener('close',negative);
}
const nativeReadonlyCursorTerminals=new WeakMap<IDBTransaction,{lease:RustChatIORoutingLease;terminal:Promise<void>}>();
/** Exact original native observation, still awaitable after negative revocation.
 * No caller-created event/receipt, private output or positive rearm grant. */
export function rustChatOpenTerminal(lease:RustChatIORoutingLease,request:IDBOpenDBRequest):Promise<void>{
  const original=nativeChatRequests.get(request);if(!original||original.lease!==lease)throw Error('invalidated_snapshot');return original.terminal;
}
export function rustChatReadonlyCursorTerminal(lease:RustChatIORoutingLease,transaction:IDBTransaction):Promise<void>{
  const original=nativeReadonlyCursorTerminals.get(transaction);if(!original||original.lease!==lease)throw Error('invalidated_snapshot');return original.terminal;
}
/** Fixed readonly local cursor resources on the SAME admitted original Root.
 * Checkpoint reads gain no write permission and never enroll another database. */
export function createRustChatReadonlyCursorTransaction(lease:RustChatIORoutingLease,database:IDBDatabase,stores:readonly string[]):IDBTransaction {
  const owned=currentRustChatLease(lease);
  if(nativeChatConnections.get(database)!==owned)throw Error('invalidated_snapshot');
  if(!(stores.length===1&&stores[0]==='messages'||stores.length===2&&stores[0]==='chats'&&stores[1]==='chat_compression_checkpoints'))throw Error('invalid_request');
  const tx=observeCreatedChatTransaction(database.transaction([...stores],'readonly'),database,false,undefined,undefined);
  const terminal=new Promise<void>(resolve=>{
    const finish=(event:Event)=>{
      if(!isTrustedTarget(event,tx))return;
      tx.removeEventListener('complete',finish);tx.removeEventListener('abort',finish);resolve();
    };
    tx.addEventListener('complete',finish);tx.addEventListener('abort',finish);
  });
  nativeReadonlyCursorTerminals.set(tx,{lease,terminal});
  owned.state.transactions.add(tx);owned.state.pending.add(terminal);
  void terminal.then(()=>{owned.state.transactions.delete(tx);owned.state.pending.delete(terminal);});
  return tx;
}
export function createRustChatTransaction(lease: RustChatIORoutingLease, database: IDBDatabase,
  stores: string | string[], mode: IDBTransactionMode): IDBTransaction {
  const owned = currentRustChatLease(lease);
  if (nativeChatConnections.get(database) !== owned) throw Error('invalidated_snapshot');
  const names = typeof stores === 'string' ? [stores] : stores;
  if (!names.length || names.some(name => name !== 'chats' && name !== 'messages' && name !== 'pending_sync_changes')) throw Error('invalid_request');
  // No new IO is exposed before its independently trusted terminal observer.
  const tx = observeCreatedChatTransaction(database.transaction(stores, mode), database, mode === 'readwrite', undefined, undefined);
  let terminal: Promise<unknown>;
  if (mode === 'readwrite') terminal = localChatWriteTerminal(tx);
  else terminal = new Promise<void>(resolve => {
    const finish = (event: Event) => {
      if (!isTrustedTarget(event, tx)) return;
      tx.removeEventListener('complete', finish); tx.removeEventListener('abort', finish); resolve();
    };
    tx.addEventListener('complete', finish); tx.addEventListener('abort', finish);
  });
  owned.state.transactions.add(tx); owned.state.pending.add(terminal);
  void terminal.then(() => { owned.state.transactions.delete(tx); owned.state.pending.delete(terminal); });
  return tx;
}

/** One ChatDatabase factory in this realm. Retiring never grants Rust authority.
 * No new connection or delayed legacy callback may reopen this factory. */
export class LegacyChatDatabaseGate {
  private retired = false;
  private connectionLineage = 0;
  noteConnectionAssignment():void{this.connectionLineage++;}
  captureCleanupLineage():()=>void{
    if(this.invalidated)throw Error('invalidated_snapshot');
    const original=this.connectionLineage;
    return ()=>{if(this.invalidated||this.connectionLineage!==original)throw Error('invalidated_snapshot');};
  }
  private connection: IDBDatabase | null = null;
  private drained = false;
  private invalidated = false;
  private readonly rustRoots = new Set<RustChatIORoot>();
  attachRustRoot(root: RustChatIORoot): void {
    if (!this.retired || !this.drained || this.invalidated) throw Error('legacy_chat_drain_incomplete');
    currentRustChatRoot(root); this.rustRoots.add(root);
  }
  assertConnectionVersion(database: IDBDatabase): void {
    if (this.invalidated || !this.connection || database.version !== this.connection.version) throw Error('invalidated_snapshot');
  }
  /** Private cleanup lane: revoke every bound real root and consume its exact
   * drain receipt before clearing. No public bypass flag or account grant. */
  hasRustRoots():boolean{return this.rustRoots.size>0;}
  cleanupDrain(): Promise<void> | null {
    if (!this.rustRoots.size) return null;
    const roots = [...this.rustRoots];
    for (const root of roots) revokeRustChatIORoot(root);
    return Promise.all(roots.map(async root => {
      const receipt = await revokeAndDrainRustChatIORoot(root);
      if (nativeChatReceipts.get(receipt) !== nativeChatRoots.get(root)) throw Error('invalidated_snapshot');
    })).then(() => undefined);
  }
  async clearChatData(database: IDBDatabase, cleanupCurrent: () => void): Promise<void> {
    const lineageCurrent=this.hasRustRoots()?this.captureCleanupLineage():()=>undefined;
    cleanupCurrent();lineageCurrent();
    const drain = this.cleanupDrain(); if (drain) await drain;
    cleanupCurrent();lineageCurrent();
    const stores = ['chats', 'messages', 'pending_sync_changes'];
    // Only this fixed clear operation bypasses retired legacy admission. The
    // transaction is never exposed, so this cannot become a late-write route.
    const tx = observeCreatedChatTransaction(database.transaction(stores, 'readwrite'), database, true, undefined, undefined);
    try {
      for (const name of stores) if (database.objectStoreNames.contains(name)) tx.objectStore(name).clear();
    } catch (error) {
      try { tx.abort(); } catch { /* Still await the actual native terminal. */ }
      await localChatWriteTerminal(tx); throw error;
    }
    const terminal = await localChatWriteTerminal(tx);
    if (terminal.outcome !== 'complete') throw Error('storage_failed');
  }

  bind(database: IDBDatabase): void {
    this.connectionLineage++;
    if (this.retired) {
      this.invalidated = true; this.drained = false;
      // Remember the replacement too: direct tracked mutators must not bypass
      // the original factory by receiving a repaired/reopened connection.
      legacyChatFactories.set(database, this);
      throw Error('legacy_chat_writer_retired');
    }
    const owner = legacyChatFactories.get(database);
    if (owner && owner !== this) throw Error('invalidated_snapshot');
    legacyChatFactories.set(database, this);
  }
  assertAdmission(): void {
    if (this.retired) throw Error('legacy_chat_writer_retired');
  }
  create(database: IDBDatabase, stores: string | string[], mode: IDBTransactionMode): IDBTransaction {
    const names = typeof stores === 'string' ? [stores] : stores;
    if (mode === 'readwrite' && names.some(name => name === 'chats' || name === 'messages' || name === 'pending_sync_changes' || name === 'message_highlights')) {
      this.assertAdmission();
    }
    return createTrackedChatTransaction(database, stores, mode);
  }
  async retireAndDrain(database: IDBDatabase, current: () => void,
    options?: { signal: AbortSignal; timeoutMs: number }): Promise<void> {
    const timeoutMs = options?.timeoutMs ?? 30000;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000) throw Error('invalid_drain_timeout');
    current();
    if (options?.signal.aborted) throw Error('cancelled');
    this.bind(database);
    if (this.retired) throw Error('legacy_chat_writer_retired');
    this.retired = true;
    this.connection = database;
    const negative=(event:Event)=>{
      if(!isTrustedTarget(event,database))return;
      this.invalidated=true;this.drained=false;
      for(const root of this.rustRoots)revokeRustChatIORoot(root);
    };
    database.addEventListener?.('versionchange',negative);
    database.addEventListener?.('close',negative);
    const snapshot = capturePendingLocalChatWrites(database);
    // Existing user writes finish naturally. Aborting them here could discard
    // data whose delayed retry has just lost legacy admission.
    const terminals = Promise.all(chatWriteSnapshots.get(snapshot)!.map(localChatWriteTerminal));
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abort = () => {};
    const cancelled = new Promise<never>((_, reject) => {
      abort = () => reject(Error('cancelled'));
      options?.signal.addEventListener('abort', abort, {once:true});
      if (options?.signal.aborted) abort();
      timer = setTimeout(() => reject(Error('legacy_chat_drain_timeout')), timeoutMs);
    });
    try {
      const outcomes = await Promise.race([terminals, cancelled]);
      if (outcomes.some(terminal => terminal.outcome !== 'complete')) throw Error('legacy_chat_drain_failed');
      current();
      if (options?.signal.aborted || this.invalidated || this.connection !== database) throw Error('invalidated_snapshot');
      // Only this successfully awaited original invocation can release the IO
      // gate. A later native terminal after timeout cannot flip this state.
      this.drained = true;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      options?.signal.removeEventListener('abort', abort);
    }
  }
}

/** Local IO lifetime only. The caller must eventually supply actual Rust/session
 * authority through current; this token does not create that authority. No
 * production writer currently opens a scope or opts into its gate.
 * Revoke synchronously, then await the returned drain outside auth/Rust leases.
 */
export function openLocalChatWriteScope(database: IDBDatabase, signal: AbortSignal,
  current: () => void): { scope: LocalChatWriteScope; revokeAndDrain: () => Promise<void> } {
  const state: ChatWriteState = { ...makeState(signal, current), database, transactions: new Set() };
  const scope = opaqueLease() as LocalChatWriteScope;
  chatWriteScopes.set(scope, state);
  const abortTransactions = () => {
    for (const transaction of state.transactions) {
      try { transaction.abort(); } catch { /* Await its terminal event even if already committing. */ }
    }
  };
  state.controller.signal.addEventListener("abort", abortTransactions, { once: true });
  let closing: Promise<void> | undefined;
  const revokeAndDrain = () => {
    // revokeLease invalidates/aborts synchronously before its first await.
    closing ??= revokeLease(state).finally(() => {
      signal.removeEventListener("abort", onAbort);
      state.controller.signal.removeEventListener("abort", abortTransactions);
      chatWriteScopes.delete(scope);
    });
    return closing;
  };
  const onAbort = () => { void revokeAndDrain(); };
  signal.addEventListener("abort", onAbort, { once: true });
  if (signal.aborted) onAbort();
  return { scope, revokeAndDrain };
}

/** Create and observe before exposing the transaction to legacy oncomplete
 * assignments. Never adopt an existing transaction: its terminal event may have
 * passed already. Legacy calls remain ungated, including logout cleanup.
 * Only chats/messages readwrite IO is counted; no other effect is attested.
 */
export function createTrackedChatTransaction(database: IDBDatabase, storeNames: string | string[],
  mode: IDBTransactionMode, scope?: LocalChatWriteScope): IDBTransaction {
  const names = typeof storeNames === "string" ? [storeNames] : storeNames;
  const tracked = mode === "readwrite" && names.some(name => name === "chats" || name === "messages" || name === "pending_sync_changes" || name === "message_highlights");
  if (tracked) legacyChatFactories.get(database)?.assertAdmission();
  const state = scope === undefined ? undefined : chatWriteScopes.get(scope);
  if (scope !== undefined) {
    if (!state || state.database !== database || !tracked) throw new Error("invalidated_snapshot");
    checkLease(state);
  }
  const transaction = database.transaction(storeNames, mode);
  return observeCreatedChatTransaction(transaction, database, tracked, scope, state);
}

/** Internal creation observer, called synchronously before exposing native IO. */
function observeCreatedChatTransaction(transaction: IDBTransaction, database: IDBDatabase,
  tracked: boolean, scope: LocalChatWriteScope | undefined, state: ChatWriteState | undefined): IDBTransaction {
  if (!tracked) return transaction;
  const pending = pendingChatWrites.get(database) ?? new Set<IDBTransaction>();
  pendingChatWrites.set(database, pending);
  pending.add(transaction);
  state?.transactions.add(transaction);
  let settle!: (terminal: LocalChatWriteTerminal) => void;
  const terminal = new Promise<LocalChatWriteTerminal>(resolve => { settle = resolve; });
  const record: ChatWriteRecord = { scope, terminal, settled: false };
  chatWriteRecords.set(transaction, record);
  state?.pending.add(terminal);
  let errorObserved = false;
  const onError = (event: Event) => {
    try { nativeType.call(event); if (event.isTrusted !== true) return; } catch { return; }
    // A bubbled request error may be preventDefault'ed. It is not evidence of
    // termination; the subsequent complete/abort event owns drain settlement.
    errorObserved = true;
  };
  const onTerminal = (event: Event) => {
    // Synthetic dispatch cannot attest IndexedDB termination. Only the browser
    // can emit a trusted complete/abort event whose original target is this IO.
    if (!isTrustedTarget(event, transaction)) return;
    record.settled = true;
    pending.delete(transaction);
    state?.transactions.delete(transaction);
    state?.pending.delete(terminal);
    transaction.removeEventListener("error", onError);
    transaction.removeEventListener("complete", onTerminal);
    transaction.removeEventListener("abort", onTerminal);
    settle(Object.freeze({ outcome: event.type === "complete" ? "complete" : "abort",
      error: transaction.error, errorObserved }));
  };
  transaction.addEventListener("error", onError);
  transaction.addEventListener("complete", onTerminal);
  transaction.addEventListener("abort", onTerminal);
  return transaction;
}

/** Strict opt-in boundary for a future Rust writer. Unknown, copied, legacy and
 * other-scope transactions cannot acquire provenance after creation. This does
 * not validate Rust ownership or gate any existing mutator.
 */
export function assertScopedLocalChatWrite(transaction: IDBTransaction, scope: LocalChatWriteScope): void {
  const record = chatWriteRecords.get(transaction);
  if (!record) throw new Error("untracked_chat_write_transaction");
  const state = chatWriteScopes.get(scope);
  if (!state || record.scope !== scope || record.settled) throw new Error("invalidated_snapshot");
  checkLease(state);
}

export function localChatWriteTerminal(transaction: IDBTransaction): Promise<LocalChatWriteTerminal> {
  const record = chatWriteRecords.get(transaction);
  if (!record) throw new Error("untracked_chat_write_transaction");
  return record.terminal;
}

/** A census of current observed transactions in this JS realm and connection,
 * not an exclusive writer handoff. Later writes, queued sends/recovery/drafts,
 * optimistic/remote effects and stale tabs are outside this snapshot. No lock,
 * auth lease, broadcast silence or copied status can enlarge that guarantee.
 */
export function capturePendingLocalChatWrites(database: IDBDatabase): LocalChatWriteSnapshot {
  const snapshot = opaqueLease() as LocalChatWriteSnapshot;
  chatWriteSnapshots.set(snapshot, [...(pendingChatWrites.get(database) ?? [])]);
  return snapshot;
}

/** Abort immediately; resolve only after every captured real terminal event.
 * This never queues cleanup behind a revoked scope and never closes the DB.
 */
export function abortAndDrainLocalChatWrites(snapshot: LocalChatWriteSnapshot): Promise<readonly LocalChatWriteTerminal[]> {
  const transactions = chatWriteSnapshots.get(snapshot);
  if (!transactions) throw new Error("invalidated_snapshot");
  for (const transaction of transactions) {
    if (!chatWriteRecords.get(transaction)!.settled) {
      try { transaction.abort(); } catch { /* Still wait for complete/abort. */ }
    }
  }
  return Promise.all(transactions.map(localChatWriteTerminal));
}

/** Original resource closures for additive draft IO; no JSON/status authority. */
export interface RustChatIOPorts {
  current():void;
  open():IDBOpenDBRequest;
  transaction(database:IDBDatabase,stores:string|string[],mode:IDBTransactionMode):IDBTransaction;
}
const rustChatIOPorts=new WeakMap<object,{lease:RustChatIORoutingLease;factory:IDBFactory}>();
export function assertRustChatIORoutingLease(root:RustChatIORoot,lease:RustChatIORoutingLease,factory:IDBFactory):void {
 const actual=currentRustChatLease(lease,factory);if(actual.root!==root)throw Error('invalidated_snapshot');
}
export function createRustChatIOPorts(lease:RustChatIORoutingLease,factory:IDBFactory):RustChatIOPorts {
  currentRustChatLease(lease,factory);
  const ports=Object.freeze({current:()=>{currentRustChatLease(lease,factory);},
    open:()=>createRustChatOpenRequest(lease,factory),
    transaction:(database:IDBDatabase,stores:string|string[],mode:IDBTransactionMode)=>createRustChatTransaction(lease,database,stores,mode)});
  rustChatIOPorts.set(ports,{lease,factory});return ports;
}
export function assertRustChatIOPorts(ports:RustChatIOPorts):void {
  const original=rustChatIOPorts.get(ports);
  if(!original)throw Error('invalidated_snapshot');currentRustChatLease(original.lease,original.factory);
}

/** Negative-only SAME original ports/Root/factory association. No structural
 * current callback or copied owner/status can install an inventory IO route. */
export function assertRustChatIOPortsRoot(ports:RustChatIOPorts,root:RustChatIORoot,factory:IDBFactory):void{
 const original=rustChatIOPorts.get(ports);if(!original||original.factory!==factory)throw Error('invalidated_snapshot');
 const actual=currentRustChatLease(original.lease,factory);if(actual.root!==root)throw Error('invalidated_snapshot');
 assertRustChatIORootFactory(root,factory);
 if(currentRustChatLease(original.lease,factory)!==actual||actual.root!==root)throw Error('invalidated_snapshot');
 assertRustChatIOPortsNegative(ports);
}
/** Callback-free original ports/lease/Root/factory negatives. Never admission,
 * IO, read/publication or a native terminal/durability acknowledgement. */
export function assertRustChatIOPortsNegative(ports:RustChatIOPorts):void{
 const original=rustChatIOPorts.get(ports);if(!original)throw Error('invalidated_snapshot');
 const actual=nativeChatLeases.get(original.lease);if(!actual||actual.state.factory!==original.factory)throw Error('invalidated_snapshot');
 assertRustChatIORootResource(actual.root);
 if(nativeChatRoots.get(actual.root)!==actual.state)throw Error('invalidated_snapshot');
}
