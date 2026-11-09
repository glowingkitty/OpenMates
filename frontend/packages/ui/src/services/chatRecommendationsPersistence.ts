/**
 * Shell side of chat Recommendations: runs the Rust reconcile step, encrypts the
 * per-chat ChatRecommendationsState with the chat key, stores it in
 * chats.encrypted_recommendations and syncs it with update_post_processing_metadata.
 *
 * Recommendations exist only in Rust core builds (VITE_OPENMATES_RUST_CORE=1). The Rust
 * wrapper is imported only inside that guard so flag-off bundles carry no Rust code;
 * flag-off callers check RECOMMENDATIONS_IN_BUILD and do nothing.
 * Duplicate/dismiss policy and event parsing live only in the Rust core.
 * Plan: docs/plans/chat-recommendations/plan.yml (D-7, wire_contract.client_storage)
 */
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { decryptWithChatKey, encryptWithChatKey } from './encryption/MessageEncryptor';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { persistGeneratedChatMetadata } from './generatedChatMetadataPersistence';
import { listPersonalRuleDocuments } from './ruleDocumentService';
import { parseRuleDocument } from '../utils/ruleDocuments';
import {
  emptyChatRecommendationsState,
  getChatRecommendations,
  nowSeconds,
  parseChatRecommendationsState,
  setChatRecommendations,
  withRecommendationRemoved,
} from '../stores/chatRecommendationsStore';
import type {
  ChatRecommendation,
  ChatRecommendationsState,
  LocalMemoryMetadata,
} from '../types/recommendations';

/** True only in Rust core builds; every Recommendations surface checks it first. */
export const RECOMMENDATIONS_IN_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/** Rust wrapper, reachable only in flag-on builds (dead-code eliminated otherwise). */
export function rustRecommendations(): Promise<typeof import('./rustCore/recommendations/rustRecommendations')> {
  return import.meta.env.VITE_OPENMATES_RUST_CORE === '1'
    ? import('./rustCore/recommendations/rustRecommendations')
    : Promise.reject(new Error('recommendations_require_rust_core'));
}

/** Title and when-to-use of every local personal memory, Mention only included. */
export async function loadLocalMemoryMetadata(): Promise<LocalMemoryMetadata[]> {
  const documents = await listPersonalRuleDocuments();
  return documents.map((document) => {
    const fields = parseRuleDocument(document.document);
    return { id: document.id, title: fields.title, when_to_use: fields.when_to_use };
  });
}

/**
 * New state for a completed turn: incoming items reconciled by the Rust core against
 * this chat's dismissed/resolved titles and all local memories.
 */
export async function reconcileIncomingRecommendations(
  incoming: ChatRecommendation[],
  previous: ChatRecommendationsState | null,
): Promise<ChatRecommendationsState> {
  const base = previous ?? emptyChatRecommendationsState();
  const { reconcileRecommendations } = await rustRecommendations();
  const items = await reconcileRecommendations({
    incoming,
    dismissed: base.dismissed,
    resolved: base.resolved,
    local_memories: await loadLocalMemoryMetadata(),
  });
  return { ...base, items, updated_at: nowSeconds() };
}

export function encryptRecommendationsState(state: ChatRecommendationsState, chatKey: Uint8Array): Promise<string> {
  return encryptWithChatKey(JSON.stringify(state), chatKey);
}

/** Null when the ciphertext cannot be decrypted or is not a schema_version 1 state. */
export async function decryptRecommendationsState(
  encrypted: string,
  chatKey: Uint8Array,
  chatId: string,
): Promise<ChatRecommendationsState | null> {
  const plaintext = await decryptWithChatKey(encrypted, chatKey, { chatId, fieldName: 'encrypted_recommendations' });
  return plaintext ? parseChatRecommendationsState(plaintext) : null;
}

/** Stored state of a chat, decrypted on this device (null when absent or unreadable). */
export async function readStoredRecommendations(chatId: string): Promise<ChatRecommendationsState | null> {
  const chat = await chatDB.getChat(chatId);
  if (!chat?.encrypted_recommendations) return null;
  const chatKey = await chatKeyManager.getKey(chatId);
  if (!chatKey) return null;
  const state = await decryptRecommendationsState(chat.encrypted_recommendations, chatKey, chatId);
  if (!state) console.warn(`[ChatRecommendations] Stored recommendations for chat ${chatId} are unreadable`);
  return state;
}

/** Loads the stored state into the store (chat open, reload, other device). */
export async function hydrateChatRecommendations(chatId: string): Promise<void> {
  if (!RECOMMENDATIONS_IN_BUILD) return;
  setChatRecommendations(chatId, await readStoredRecommendations(chatId));
}

/**
 * Encrypts and stores the state locally, then syncs ciphertext only
 * (chat_id + encrypted_recommendations) to the server.
 */
async function persistRecommendationsOnly(chatId: string, state: ChatRecommendationsState): Promise<void> {
  const chatKey = await chatKeyManager.getKey(chatId);
  if (!chatKey) throw new Error('recommendations_chat_key_unavailable');
  if (!(await ensureChatKeySafeForWrite(chatId, chatKey, 'chat recommendations update'))) {
    throw new Error('recommendations_chat_key_unsafe');
  }
  const storedChat = await chatDB.getChat(chatId);
  if (!storedChat) throw new Error('recommendations_chat_missing');
  const encrypted = await encryptRecommendationsState(state, chatKey);
  const persisted = await persistGeneratedChatMetadata(
    chatDB, storedChat, { encrypted_recommendations: encrypted }, () => true,
  );
  if (!persisted) throw new Error('recommendations_local_write_rejected');
  const [{ chatSyncService }, { sendChatRecommendationsStateImpl }] = await Promise.all([
    import('./chatSyncService'),
    import('./sendersSync'),
  ]);
  await sendChatRecommendationsStateImpl(
    chatSyncService, chatId, encrypted, persisted.encrypted_chat_key ?? '',
  );
}

async function removeRecommendation(chatId: string, id: string, list: 'dismissed' | 'resolved'): Promise<void> {
  if (!RECOMMENDATIONS_IN_BUILD) return;
  const current = getChatRecommendations(chatId) ?? await readStoredRecommendations(chatId);
  if (!current) return;
  const next = withRecommendationRemoved(current, id, list);
  if (!next) return;
  // Optimistic: the card updates at once; persistence errors are reported, not hidden.
  setChatRecommendations(chatId, next);
  await persistRecommendationsOnly(chatId, next);
}

/** Saved from the card: the item disappears and its title is never proposed again here. */
export function resolveChatRecommendation(chatId: string, id: string): Promise<void> {
  return removeRecommendation(chatId, id, 'resolved');
}
