import {createRustChatOpenRequest,createRustChatReadonlyCursorTransaction,rustChatOpenTerminal,rustChatReadonlyCursorTerminal} from './browserAdapters';
import type {RustChatIORoutingLease} from './browserAdapters';
/** Read-only platform IO for the deployed user_db/chats_db schema.
 * No database initialization, repair, migration, key unwrap or plaintext decode.
 * Cursor order is the existing physical IDB index order, never a TS read window.
 * Complete matching raw rows are transferred within the existing RPC byte cap;
 * oversize input refuses as a whole instead of truncating or inventing coverage.
 * Rust owns row/ID selection, interpretation and every decryption decision.
 */
import { boundedJson } from "./savedReadProtocol";
import { MAX_CHAT_UTF8_BYTES, MAX_REQUEST_MS } from "./protocol";
import type { SavedChatSelection } from "./selectedSavedChat";
const USER_DATABASE = "user_db", USER_STORE = "user_data";
const CHAT_DATABASE = "chats_db", CHAT_STORE = "chats", MESSAGE_STORE = "messages";
const CHECKPOINT_STORE = "chat_compression_checkpoints";
const FRAME_RESERVE_BYTES = 8192;

/** Caller cancellation discards this read's result, never attests that an
 * existing underlying key/IDB operation has reached its own terminal event. */
export function awaitBrowserRead<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => { signal.removeEventListener("abort", abort); reject(new Error("cancelled")); };
    signal.addEventListener("abort", abort, { once: true });
    void operation.then(value => { signal.removeEventListener("abort", abort); if (signal.aborted) abort(); else resolve(value); },
      error => { signal.removeEventListener("abort", abort); reject(error); });
    if (signal.aborted) abort();
  });
}
/** Same original native request stays owned through cancellation, blocked and
 * upgrade observations; only its independent real terminal can settle IO. */
async function existingRoutedCursorDatabase(factory:IDBFactory,name:string,signal:AbortSignal,guard:()=>void,lease:RustChatIORoutingLease):Promise<IDBDatabase>{
  guard();if(name!=='chats_db'||typeof factory.databases!=='function')throw Error('unavailable');
  const databases=await factory.databases();guard();if(signal.aborted)throw Error('cancelled');
  const version=databases.find(row=>row.name===name&&Number.isSafeInteger(row.version)&&Number(row.version)>0)?.version;
  if(version===undefined)throw Error('unavailable');
  const request=createRustChatOpenRequest(lease,factory),terminal=rustChatOpenTerminal(lease,request);
  let failure:Error|null=null;let settled=false;
  const abort=()=>{failure??=Error('cancelled');};signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
  try{
    const opened=await new Promise<IDBDatabase>((resolve,reject)=>{
      request.onblocked=()=>{failure??=Error('unavailable');};
      request.onupgradeneeded=()=>{failure??=Error('unavailable');try{request.transaction?.abort();}catch{/* Real open terminal still owns settlement. */}};
      request.onerror=()=>{if(!settled){settled=true;reject(failure??Error('unavailable'));}};
      request.onsuccess=()=>{
        const db=request.result;
        if(settled){db.close();return;}
        try{guard();if(signal.aborted)throw Error('cancelled');if(failure)throw failure;if(db.version!==version)throw Error('unavailable');settled=true;resolve(db);}
        catch(error){db.close();settled=true;reject(error);}
      };
    });
    // Property callbacks alone (including synthetic calls) cannot prove native
    // completion. The opaque same-request observer owns the final await.
    await terminal;try{guard();if(signal.aborted)throw Error('cancelled');return opened;}catch(error){opened.close();throw error;}
  }finally{await terminal;signal.removeEventListener('abort',abort);}
}
async function existingDatabase(factory: IDBFactory, name: string, signal: AbortSignal, guard: () => void,routingLease?:RustChatIORoutingLease): Promise<IDBDatabase> {
  if(routingLease)return existingRoutedCursorDatabase(factory,name,signal,guard,routingLease);
  guard();
  if (typeof factory.databases !== "function") throw new Error("unavailable");
  const databases = await awaitBrowserRead(factory.databases(), signal); guard();
  const observedVersion = databases.find(row => row.name === name && Number.isSafeInteger(row.version) && Number(row.version) > 0)?.version;
  if (observedVersion === undefined) throw new Error("unavailable");
  return new Promise((resolve, reject) => {
    let settled = false;
    const abort = () => { if (!settled) { settled = true; reject(new Error("cancelled")); } };
    signal.addEventListener("abort", abort, { once: true });
    const request = factory.open(name);
    const fail = () => { if (!settled) { settled = true; signal.removeEventListener("abort", abort); reject(new Error("unavailable")); } };
    request.onupgradeneeded = () => { request.transaction?.abort(); fail(); };
    request.onblocked = request.onerror = fail;
    request.onsuccess = () => {
      const database = request.result;
      signal.removeEventListener("abort", abort);
      if (settled || signal.aborted) { database.close(); if (!settled) abort(); return; }
      try { guard(); if (database.version !== observedVersion) throw new Error("unavailable"); settled = true; resolve(database); } catch (error) { database.close(); settled = true; reject(error); }
    };
    if (signal.aborted) abort();
  });
}
type IssueRead<T> = (transaction: IDBTransaction, fail: (error: unknown) => void) => () => T;
/** One readonly transaction on an already opened existing database; settles only
 * on the transaction's own complete/abort terminal. */
function transactExisting<T>(database: IDBDatabase, stores: readonly string[], lifetime: AbortSignal, current: () => void,
  issue: IssueRead<T>, routingLease?: RustChatIORoutingLease): { result: Promise<T>; terminal: Promise<void> | null } {
  if (stores.some(store => !database.objectStoreNames.contains(store))) throw new Error("unavailable");
  const transaction = routingLease ? createRustChatReadonlyCursorTransaction(routingLease, database, stores) : database.transaction([...stores], "readonly");
  const terminal = routingLease ? rustChatReadonlyCursorTerminal(routingLease, transaction) : null;
  const result = new Promise<T>((resolve, reject) => {
    let failure: unknown = null, read: (() => T) | null = null;
    const fail = (error: unknown) => { failure ??= error; try { transaction.abort(); } catch { /* Terminal handler owns settlement. */ } };
    const cancelled = () => fail(new Error("cancelled"));
    const cleanup = () => lifetime.removeEventListener("abort", cancelled);
    transaction.onabort = () => { cleanup(); reject(failure ?? new Error("storage_failed")); };
    transaction.onerror = () => { failure ??= new Error("storage_failed"); };
    transaction.oncomplete = () => { cleanup(); try { current(); if (failure) throw failure; if (!read) throw new Error("unavailable"); resolve(read()); } catch (error) { reject(error); } };
    lifetime.addEventListener("abort", cancelled, { once: true });
    try { current(); read = issue(transaction, fail); } catch (error) { fail(error); }
  });
  return { result, terminal };
}
export async function readExisting<T>(factory: IDBFactory, name: string, stores: readonly string[], signal: AbortSignal,
  guard: () => void, issue: IssueRead<T>, routingLease?:RustChatIORoutingLease): Promise<T> {
  const lifetime = new AbortController();
  const abort = () => lifetime.abort();
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, MAX_REQUEST_MS);
  let database: IDBDatabase | null = null;let originalCursorTerminal:Promise<void>|null=null;
  const current = () => { if (signal.aborted || lifetime.signal.aborted) throw new Error("cancelled"); guard(); };
  try {
    current(); database = await existingDatabase(factory, name, lifetime.signal, current,routingLease); current();
    database.onversionchange = () => { database?.close(); abort(); };
    const transaction = transactExisting(database, stores, lifetime.signal, current, issue, routingLease);
    originalCursorTerminal = transaction.terminal;
    return await transaction.result;
  } finally { try{if(originalCursorTerminal){await originalCursorTerminal;current();}}finally{clearTimeout(timer); signal.removeEventListener("abort", abort); lifetime.abort(); database?.close();} }
}
/**
 * One existing database connection held for a platform lifetime, so repeated
 * readonly checks do not each pay `databases()` + open (both serialize on the
 * origin's IndexedDB backend and delay the TS boot's own IDB work).
 * Opened like `readExisting` (existing version only, no create/upgrade). Any
 * `versionchange` (TS upgrade, deleteDatabase on logout) or forced close closes
 * it at once and invalidates it for good: every later read rejects
 * `invalidated_snapshot`; it never reopens. Not for routed (lease) cursor IO.
 */
export interface HeldExistingDatabase {
  read<T>(stores: readonly string[], signal: AbortSignal, guard: () => void, issue: IssueRead<T>): Promise<T>;
  close(): void;
}
export function holdExistingDatabase(factory: IDBFactory, name: string): HeldExistingDatabase {
  const lifetime = new AbortController();
  let opening: Promise<IDBDatabase> | null = null, database: IDBDatabase | null = null, lost = false;
  const lose = () => { lost = true; database?.close(); database = null; lifetime.abort(); };
  // The shared open belongs to the holder, not to its first caller: each caller
  // re-checks its own guard after the await.
  const open = (signal: AbortSignal): Promise<IDBDatabase> => {
    opening ??= existingDatabase(factory, name, lifetime.signal, () => { if (lost) throw new Error("invalidated_snapshot"); }).then((opened) => {
      if (lost) { opened.close(); throw new Error("invalidated_snapshot"); }
      opened.onversionchange = lose;
      opened.onclose = lose;
      database = opened;
      return opened;
    });
    // A failed open is not retried: fail closed.
    opening.catch(() => { lost = true; });
    return awaitBrowserRead(opening, signal);
  };
  return {
    async read(stores, signal, guard, issue) {
      if (lost) throw new Error("invalidated_snapshot");
      const operation = new AbortController();
      const abort = () => operation.abort();
      for (const source of [signal, lifetime.signal]) { source.addEventListener("abort", abort, { once: true }); if (source.aborted) abort(); }
      const timer = setTimeout(abort, MAX_REQUEST_MS);
      const current = () => { if (lost) throw new Error("invalidated_snapshot"); if (operation.signal.aborted) throw new Error("cancelled"); guard(); };
      try {
        current(); const opened = await open(operation.signal); current();
        return await transactExisting(opened, stores, operation.signal, current, issue).result;
      } finally {
        clearTimeout(timer); signal.removeEventListener("abort", abort); lifetime.signal.removeEventListener("abort", abort);
      }
    },
    close: lose,
  };
}
function issueProfileOwner(transaction: IDBTransaction): () => unknown {
  let owner: unknown;
  const request = transaction.objectStore(USER_STORE).get("id");
  request.onsuccess = () => { owner = request.result; };
  return () => owner;
}
export async function readExistingProfileOwner(factory: IDBFactory, signal: AbortSignal, guard: () => void): Promise<unknown> {
  return readExisting(factory, USER_DATABASE, [USER_STORE], signal, guard, issueProfileOwner);
}
/** Same read on a platform-held `user_db` connection (see holdExistingDatabase). */
export function holdExistingProfileDatabase(factory: IDBFactory): HeldExistingDatabase { return holdExistingDatabase(factory, USER_DATABASE); }
export async function readHeldProfileOwner(held: HeldExistingDatabase, signal: AbortSignal, guard: () => void): Promise<unknown> {
  return held.read([USER_STORE], signal, guard, issueProfileOwner);
}
/** Transfer all matching rows. Current Rust may refuse >20 input rows or legacy
 * ID shapes; this adapter must not hide that capability gap by rewriting them.
 * Nonempty checkpoint data cannot be represented by the current local-row RPC,
 * so refuse explicitly instead of computing compression policy in TypeScript.
 */
export async function readExistingSavedChatRows(factory: IDBFactory, selected: Readonly<SavedChatSelection>, signal: AbortSignal,
  guard: () => void, keyRange: Pick<typeof IDBKeyRange, "bound" | "only"> = IDBKeyRange): Promise<unknown> {
  return readExisting(factory, CHAT_DATABASE, [CHAT_STORE, MESSAGE_STORE, CHECKPOINT_STORE], signal, guard, (transaction, fail) => {
    let metadata: Record<string, unknown> | null = null, bytes = FRAME_RESERVE_BYTES;
    const messages: unknown[] = [];
    const countBytes = (row: unknown) => {
      if (!boundedJson(row)) throw new Error("unavailable");
      bytes += new TextEncoder().encode(JSON.stringify(row)).byteLength + 1;
      if (bytes > MAX_CHAT_UTF8_BYTES) throw new Error("unavailable");
    };
    const request = transaction.objectStore(CHAT_STORE).get(selected.chatId);
    request.onsuccess = () => {
      try {
        guard(); const raw: unknown = request.result;
        if (typeof raw !== "object" || raw === null || (raw as Record<string, unknown>).chat_id !== selected.chatId) throw new Error("unavailable");
        // IDB's chat_id column maps to the shared DTO's id; preserve a conflicting
        // existing id for Rust to refuse rather than silently repairing it here.
        metadata = { ...raw as Record<string, unknown>, id: (raw as Record<string, unknown>).id ?? selected.chatId };
        // Match deployed getRawChat's metadata-only storage projection.
        delete metadata.messages;
        countBytes(metadata);
      } catch (error) { fail(error); }
    };
    const cursor = transaction.objectStore(MESSAGE_STORE).index("chat_id_created_at")
      .openCursor(keyRange.bound([selected.chatId, -Infinity], [selected.chatId, Infinity]), "next");
    cursor.onsuccess = () => {
      const row = cursor.result; if (!row) return;
      try { guard(); countBytes(row.value); messages.push(row.value); row.continue(); } catch (error) { fail(error); }
    };
    const checkpoints = transaction.objectStore(CHECKPOINT_STORE).index("chat_id").count(keyRange.only(selected.chatId));
    checkpoints.onsuccess = () => { if (checkpoints.result !== 0) fail(new Error("local_checkpoint_io_unsupported")); };
    return () => {
      if (!metadata) throw new Error("unavailable");
      const packet = { chat_metadata: metadata, messages, wrappers: [], boundary: null };
      if (!boundedJson(packet)) throw new Error("unavailable");
      return packet;
    };
  });
}
