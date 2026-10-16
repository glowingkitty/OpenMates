/**
 * Durable identity and replay guard for post-admission draft deletion.
 * A versioned offline row survives a tab reload while the routing context runs.
 * The row key binds the delete to its account, admitted turn and message journal.
 * Tab-local holds prevent the regular queue flush from overtaking that context.
 * After reload, the persisted admission journal provides the same ordering fence.
 * The server sees an ordinary versioned delete_draft offline change.
 */
import { get } from "svelte/store";
import { userProfile } from "../stores/userProfile";
import { chatDB } from "./db";
import { isDraftContextDispatchActive } from "./draftContextDispatchBarrier";
import { getApiEndpoint } from "../config/api";

const PREFIX = "draft-context-delete-v1:";
const held = new Set<string>();

export function makeDeferredDraftDeleteId(turnId: string, messageId: string): string {
  const owner = get(userProfile).user_id;
  if (!owner) throw new Error("Cannot queue draft deletion without an account");
  return `${PREFIX}${owner}:${encodeURIComponent(getApiEndpoint("/v1"))}:${turnId}:${messageId}:${crypto.randomUUID()}`;
}

export function parseDeferredDraftDeleteId(id: string): { owner: string; api: string; turnId: string; messageId: string } | null {
  if (!id.startsWith(PREFIX)) return null;
  const [owner, encodedApi, turnId, messageId, nonce, ...rest] = id.slice(PREFIX.length).split(":");
  if (!owner || !encodedApi || !turnId || !messageId || !nonce || rest.length) return null;
  try { return { owner, api: decodeURIComponent(encodedApi), turnId, messageId }; }
  catch { return null; }
}

export function holdDeferredDraftDelete(id: string): void { held.add(id); }
export function releaseDeferredDraftDelete(id: string): void { held.delete(id); }

export function isDeferredDraftDeleteFencedNow(id: string, chatId: string): boolean {
  const marker = parseDeferredDraftDeleteId(id);
  return !!marker && (marker.owner !== get(userProfile).user_id ||
    marker.api !== getApiEndpoint("/v1") || held.has(id) ||
    isDraftContextDispatchActive(chatId, marker.turnId));
}

async function hasPendingAdmissionJournal(messageId: string, chatId: string): Promise<boolean> {
  const transaction = await chatDB.getTransaction("messages", "readonly");
  return new Promise((resolve, reject) => {
    const request = transaction.objectStore("messages").get(messageId);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const row = request.result as { chat_id?: string; pending_encrypted_turn_preflight_v1?: unknown } | undefined;
      resolve(row?.chat_id === chatId && typeof row.pending_encrypted_turn_preflight_v1 === "string");
    };
  });
}

export async function mayReplayDeferredDraftDelete(id: string, chatId: string): Promise<boolean> {
  const marker = parseDeferredDraftDeleteId(id);
  if (!marker) return true;
  if (isDeferredDraftDeleteFencedNow(id, chatId)) return false;
  try { return !(await hasPendingAdmissionJournal(marker.messageId, chatId)); }
  catch {
    console.warn("[ChatSyncService:Senders] Deferred draft journal lookup unavailable");
    return false;
  }
}
