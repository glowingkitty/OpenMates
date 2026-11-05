import type {RustChatIORoutingLease} from './browserAdapters';
/** Executes Rust-issued readonly IndexedDB plans, with no window or crypto policy.
 * Rust supplies physical bounds, order, payload count and packet byte budget.
 * A key-only sentinel reports local scan termination without hydrating old bodies.
 * The caller owns genuine profile/selection/lifecycle checks before and after IO.
 * Every result waits for the owned readonly transaction complete/abort terminal.
 * No database initialization, writes, decryption, PII or schema migration occurs.
 */
import { readExisting } from "./existingSavedChatIO";
import { boundedJson, validReadMessageId } from "./savedReadProtocol";
const DATABASE = "chats_db", METADATA = "chats", MESSAGES = "messages", CHECKPOINTS = "chat_compression_checkpoints";
const INDEX = "chat_id_created_at";
import { parseBrowserLocalReadPlan } from "./protocol";
import type { LocalCursorBound } from "./protocol";
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function integer(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function identifier(value: unknown): value is string { return validReadMessageId(value); }
/** Existing TS rows may hold `undefined`-valued properties (object spreads).
 * The packet is JSON, where those properties do not exist, so drop them before
 * the strict JSON shape check; every other non-JSON value is still refused. */
function jsonRow(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(jsonRow);
  if (!record(value)) return value;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return value;
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) if (item !== undefined) out[key] = jsonRow(item);
  return out;
}
function position(cursor: IDBCursor): { createdAt: number; messageId: string } {
  const indexKey: unknown = cursor.key, primaryKey: unknown = cursor.primaryKey;
  if (!Array.isArray(indexKey) || indexKey.length !== 2 || !integer(indexKey[1]) || !identifier(primaryKey)) throw new Error("unavailable");
  return { createdAt: indexKey[1], messageId: primaryKey };
}
function compare(current: { createdAt: number; messageId: string }, bound: LocalCursorBound): number {
  if (current.createdAt !== bound.createdAt) return current.createdAt < bound.createdAt ? -1 : 1;
  if (bound.messageId === null) return 0;
  return current.messageId === bound.messageId ? 0 : current.messageId < bound.messageId ? -1 : 1;
}
/** Generic plan execution only. Bind the guard to the existing admitted profile,
 * request and selection; owner labels in the plan cannot supply that authority. */
export async function executeBrowserLocalReadPlan(factory: IDBFactory, encoded: string, signal: AbortSignal,
  guard: () => void, keyRange: Pick<typeof IDBKeyRange, "bound"> = IDBKeyRange,routingLease?:RustChatIORoutingLease): Promise<string> {
  guard(); if (signal.aborted) throw new Error("cancelled"); const plan = parseBrowserLocalReadPlan(encoded);
  const stores = (plan.kind === "metadata" || plan.kind === "owned_metadata") ? [METADATA, CHECKPOINTS] : [MESSAGES];
  const reply = await readExisting<Record<string, unknown>>(factory, DATABASE, stores, signal, guard, (transaction, fail) => {
    const base = { version: 1, kind: plan.kind, operationId: plan.operationId, databaseVersion: transaction.db.version };
    let bytes = 1024;
    const count = (row: unknown) => {
      if (!boundedJson(row)) throw new Error("unavailable_non_json_row");
      bytes += new TextEncoder().encode(JSON.stringify(row)).byteLength + 1;
      if (bytes > plan.maxPacketBytes) throw new Error("unavailable_packet_budget");
    };
    if ((plan.kind === "metadata" || plan.kind === "owned_metadata")) {
      let metadata: Record<string, unknown> | null = null; const checkpoints: unknown[] = [];
      const request = transaction.objectStore(METADATA).get(plan.chatId);
      request.onsuccess = () => { try {
        guard(); const raw: unknown = jsonRow(request.result);
        if(raw===undefined&&plan.kind==="owned_metadata")return;
        if (!record(raw) || raw.chat_id !== plan.chatId) throw new Error("unavailable_missing_chat");
        metadata = { ...raw, id: raw.id ?? plan.chatId }; delete metadata.messages; count(metadata);
      } catch (error) { fail(error); } };
      const cursor = transaction.objectStore(CHECKPOINTS).index(INDEX)
        .openCursor(keyRange.bound([plan.chatId, -Infinity], [plan.chatId, Infinity]), "next");
      cursor.onsuccess = () => { const current = cursor.result; if (!current) return; try {
        guard(); if (checkpoints.length >= plan.maxCheckpointRows) throw new Error("unavailable_checkpoint_rows");
        const checkpoint = jsonRow(current.value); count(checkpoint); checkpoints.push(checkpoint); current.continue();
      } catch (error) { fail(error); } };
      return () => { if (!metadata&&(plan.kind!=="owned_metadata"||checkpoints.length!==0)) throw new Error("unavailable"); return { ...base, chat_metadata: metadata, messages: [], wrappers: [], boundary: null, compression_checkpoints: checkpoints }; };
    }
    if (plan.kind === "anchor") {
      const messages: unknown[]=[];
      const request=transaction.objectStore(MESSAGES).get(plan.anchorMessageId!);
      request.onsuccess=()=>{try{guard();if(request.result!==undefined){const anchor=jsonRow(request.result);count(anchor);messages.push(anchor);}}catch(error){fail(error);}};
      return()=>({...base,messages});
    }
    const messages: unknown[] = []; let nextKey: ReturnType<typeof position> | null = null, rangeExhausted = false;
    const lower = plan.lower, upper = plan.upper;
    const store = transaction.objectStore(MESSAGES);
    const request = store.index(INDEX).openKeyCursor(keyRange.bound([plan.chatId, lower?.createdAt ?? -Infinity],
      [plan.chatId, upper?.createdAt ?? Infinity], !!lower && lower.messageId === null && lower.open,
      !!upper && upper.messageId === null && upper.open), plan.direction);
    request.onsuccess = () => { const cursor = request.result; if (!cursor) { rangeExhausted = true; return; } try {
      guard(); if (!Array.isArray(cursor.key) || cursor.key[0] !== plan.chatId) throw new Error("unavailable");
      const current = position(cursor);
      const low = lower ? compare(current, lower) : 1, high = upper ? compare(current, upper) : -1;
      if (lower && (low < 0 || lower.open && low === 0)) {
        if (plan.direction === "prev") { rangeExhausted = true; return; }
        if (low < 0 && lower.messageId !== null) cursor.continuePrimaryKey([plan.chatId, lower.createdAt], lower.messageId);
        else cursor.continue(); return;
      }
      if (upper && (high > 0 || upper.open && high === 0)) {
        if (plan.direction === "next") { rangeExhausted = true; return; }
        if (high > 0 && upper.messageId !== null) cursor.continuePrimaryKey([plan.chatId, upper.createdAt], upper.messageId);
        else cursor.continue(); return;
      }
      if (messages.length === plan.maxPayloadRows) { nextKey = current; return; }
      const row = store.get(cursor.primaryKey);
      row.onsuccess = () => { try { guard(); const value = jsonRow(row.result); count(value); messages.push(value); cursor.continue(); } catch (error) { fail(error); } };
    } catch (error) { fail(error); } };
    return () => ({ ...base, messages, nextKey, rangeExhausted });
  },routingLease);
  guard(); if (signal.aborted) throw new Error("cancelled");
  if (!boundedJson(reply)) throw new Error("unavailable");
  const result = JSON.stringify(reply);
  if (new TextEncoder().encode(result).byteLength > plan.maxPacketBytes) throw new Error("unavailable");
  return result;
}
