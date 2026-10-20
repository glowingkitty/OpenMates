import { persistGeneratedChatMetadata } from "./generatedChatMetadataPersistence";
import { BoundedCache } from "../utils/boundedCache";
import { registerWorkspaceCacheClear, getWorkspaceCacheEpoch } from "./workspaceCacheLifecycle";
import { isChatMetadataTurnCurrent } from "./lateChatMetadataGuard";
import { get } from 'svelte/store';
import type { Chat, AIMessageUpdatePayload } from '../types/chat';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { activeTeamId } from '../stores/teamStore';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { encryptWithChatKey, decryptWithChatKey } from './encryption/MessageEncryptor';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { webSocketService } from './websocketService';
import type { ChatSynchronizationService } from './chatSyncService';

export interface ComposerGhostSuggestion {
  text: string;
  sourceMessageId: string;
  sourceUserMessageId: string;
  sourceTaskId: string;
}

export function decodeComposerGhostSuggestion(value: string): ComposerGhostSuggestion | null {
  try {
    const parsed = JSON.parse(value) as Partial<ComposerGhostSuggestion>;
    if (typeof parsed.text !== 'string' || !parsed.text.trim() || parsed.text.length > 400 ||
        typeof parsed.sourceMessageId !== 'string' || !parsed.sourceMessageId ||
        typeof parsed.sourceUserMessageId !== 'string' || !parsed.sourceUserMessageId ||
        typeof parsed.sourceTaskId !== 'string' || !parsed.sourceTaskId) return null;
    return parsed as ComposerGhostSuggestion;
  } catch {
    return null;
  }
}

export function chatAllowsComposerGhostSuggestion(chat: Chat): boolean {
  const profile = get(userProfile);
  return get(authStore).isAuthenticated && profile.follow_up_suggestions_enabled !== false &&
    !!profile.user_id && chat.user_id === profile.user_id &&
    !chat.is_incognito && !chat.is_anonymous && !chat.is_shared_by_others &&
    !chat.is_sub_chat && !chat.parent_id &&
    (get(activeTeamId) ? chat.team_id === get(activeTeamId) : !chat.team_id);
}

export async function decryptComposerGhostSuggestion(chat: Chat): Promise<ComposerGhostSuggestion | null> {
  if (!chat.encrypted_suggested_followup_message || !chatAllowsComposerGhostSuggestion(chat)) return null;
  const key = await chatKeyManager.getKey(chat.chat_id);
  if (!key) return null;
  const plaintext = await decryptWithChatKey(chat.encrypted_suggested_followup_message, key);
  return plaintext ? decodeComposerGhostSuggestion(plaintext) : null;
}

// Only successful final IDs survive until correlated post-processing arrives.
// No answer text or suggestion plaintext is retained in this bounded cache.
interface CompletedSource {
  messageId: string;
  taskId: string;
  userMessageId: string;
  epoch: number;
  revision: number;
  main: boolean;
  fallback: boolean;
  writes: Promise<void>;
}
const completedSources = new BoundedCache<string, CompletedSource>(128 * 1024, 256);
registerWorkspaceCacheClear(() => completedSources.clear());

export interface ComposerFallbackPayload {
  chat_id: string;
  task_id: string;
  user_message_id?: string;
  turn_id?: string;
  follow_up_request_suggestions: unknown;
  harmful_response: number;
}

export async function persistPostProcessingComposerFallback(
  payload: ComposerFallbackPayload,
  serviceInstance: ChatSynchronizationService,
  dispatch: (suggestion: ComposerGhostSuggestion) => void,
): Promise<void> {
  const source = completedSources.get(payload.chat_id);
  if (!source || source.epoch !== getWorkspaceCacheEpoch() || source.main || source.fallback ||
      source.taskId !== payload.task_id || source.userMessageId !== payload.user_message_id ||
      payload.harmful_response !== 0 || !Array.isArray(payload.follow_up_request_suggestions)) return;
  const text = payload.follow_up_request_suggestions.find((value: unknown) =>
    typeof value === 'string' && value.trim().length > 0 && value.trim().length <= 400)?.trim();
  if (!text) return;
  source.fallback = true;
  const final = { chat_id: payload.chat_id, message_id: source.messageId, task_id: source.taskId,
    user_message_id: source.userMessageId, is_final_chunk: true, suggested_followup_message: text } as AIMessageUpdatePayload;
  await queueSuggestion(final, serviceInstance, dispatch, source);
}

export async function persistComposerGhostSuggestion(
  payload: AIMessageUpdatePayload,
  serviceInstance: ChatSynchronizationService,
  dispatch: (suggestion: ComposerGhostSuggestion) => void,
): Promise<void> {
  if (!payload.is_final_chunk || payload.awaiting_async_skill_continuation ||
      payload.interrupted_by_revocation || payload.interrupted_by_soft_limit || payload.rejection_reason ||
      !payload.message_id || !payload.task_id || !payload.user_message_id ||
      !isChatMetadataTurnCurrent(payload.chat_id, payload.task_id, payload.user_message_id) ||
      (serviceInstance.activeAITasks.get(payload.chat_id) &&
       serviceInstance.activeAITasks.get(payload.chat_id)?.taskId !== payload.task_id)) return;
  let source = completedSources.get(payload.chat_id);
  if (!source || source.epoch !== getWorkspaceCacheEpoch() || source.messageId !== payload.message_id ||
      source.taskId !== payload.task_id || source.userMessageId !== payload.user_message_id) {
    source = { messageId: payload.message_id, taskId: payload.task_id, userMessageId: payload.user_message_id,
      epoch: getWorkspaceCacheEpoch(), revision: 0, main: false, fallback: false, writes: Promise.resolve() };
    completedSources.set(payload.chat_id, source);
  }
  const text = payload.suggested_followup_message?.trim();
  if (!text || text.length > 400 || source.main) return;
  source.main = true;
  source.revision++;
  await queueSuggestion(payload, serviceInstance, dispatch, source);
}

async function queueSuggestion(
  payload: AIMessageUpdatePayload,
  serviceInstance: ChatSynchronizationService,
  dispatch: (suggestion: ComposerGhostSuggestion) => void,
  source: CompletedSource,
): Promise<void> {
  const revision = source.revision;
  const validSource = () => source.epoch === getWorkspaceCacheEpoch()
    && completedSources.get(payload.chat_id) === source && source.revision === revision;
  // Serialize writes so an already-started fallback transaction can never finish
  // after the main suggestion's transaction and replace it.
  const write = source.writes.catch(() => undefined).then(() =>
    persistSuggestion(payload, serviceInstance, dispatch, validSource));
  source.writes = write;
  await write;
}

async function persistSuggestion(
  payload: AIMessageUpdatePayload,
  serviceInstance: ChatSynchronizationService,
  dispatch: (suggestion: ComposerGhostSuggestion) => void,
  validSource: () => boolean,
): Promise<void> {
  const ownerEpoch = getWorkspaceCacheEpoch();
  const isCurrent = () => validSource() && ownerEpoch === getWorkspaceCacheEpoch()
    && isChatMetadataTurnCurrent(payload.chat_id, payload.task_id, payload.user_message_id)
    && (!serviceInstance.activeAITasks.get(payload.chat_id)
      || serviceInstance.activeAITasks.get(payload.chat_id)?.taskId === payload.task_id);
  if (!isCurrent()) return;
  const text = payload.suggested_followup_message?.trim();
  if (!text || text.length > 400 || !payload.is_final_chunk ||
      payload.awaiting_async_skill_continuation || payload.interrupted_by_revocation ||
      payload.interrupted_by_soft_limit || payload.rejection_reason) return;
  let chat = await chatDB.getChat(payload.chat_id);
  // A very fast first turn can finish before the provisional chat shell's
  // IndexedDB write settles. Retry that narrow race without fetching history.
  for (const delay of [100, 300, 700]) {
    if (chat) break;
    await new Promise((resolve) => setTimeout(resolve, delay));
    chat = await chatDB.getChat(payload.chat_id);
  }
  if (!chat || !isCurrent() || !chatAllowsComposerGhostSuggestion(chat)) return;
  const suggestion: ComposerGhostSuggestion = {
    text, sourceMessageId: payload.message_id,
    sourceUserMessageId: payload.user_message_id, sourceTaskId: payload.task_id,
  };
  dispatch(suggestion);
  const key = await chatKeyManager.getKey(payload.chat_id);
  if (!key || !(await ensureChatKeySafeForWrite(payload.chat_id, key, 'composer ghost suggestion'))) return;
  const encrypted = await encryptWithChatKey(JSON.stringify(suggestion), key);
  if (!encrypted) return;
  // Recheck scope after every async key operation; logout or Team switches must not
  // leave a suggestion in the next account's local chat projection.
  const latest = await chatDB.getChat(payload.chat_id);
  if (!isCurrent() || !latest || !latest.encrypted_chat_key || !chatAllowsComposerGhostSuggestion(latest)) return;
  const persisted = await persistGeneratedChatMetadata(chatDB, latest,
    { encrypted_suggested_followup_message: encrypted },
    () => isCurrent() && chatAllowsComposerGhostSuggestion(latest));
  if (!persisted || !isCurrent() || !chatAllowsComposerGhostSuggestion(persisted)) return;
  const outgoing = {
    chat_id: payload.chat_id,
    source_message_id: payload.message_id,
    source_user_message_id: payload.user_message_id,
    source_task_id: payload.task_id,
    encrypted_chat_key: persisted.encrypted_chat_key,
    team_id: persisted.team_id ?? null,
    encrypted_suggested_followup_message: encrypted,
  };
  let storageConfirmed = false;
  let retryAfterStorage = false;
  let attempts = 0;
  let settled = false;
  const cleanup = () => {
    if (settled) return;
    settled = true;
    clearTimeout(expiry);
    serviceInstance.removeEventListener('aiResponseStorageConfirmed', onStorageConfirmed);
    webSocketService.off('encrypted_suggested_followup_message_not_stored', onNotStored);
    webSocketService.off('encrypted_suggested_followup_message_stored', onStored);
  };
  const send = async () => {
    if (settled || attempts >= 2) return;
    const current = await chatDB.getChat(payload.chat_id);
    if (!isCurrent() || !current || !chatAllowsComposerGhostSuggestion(current) || current.encrypted_chat_key !== outgoing.encrypted_chat_key) {
      cleanup();
      return;
    }
    attempts++;
    await webSocketService.sendMessage('encrypted_suggested_followup_message', outgoing);
  };
  const onStorageConfirmed = (event: Event) => {
    const detail = (event as CustomEvent<{ chatId: string; messageId: string }>).detail;
    if (detail.chatId !== payload.chat_id || detail.messageId !== payload.message_id) return;
    storageConfirmed = true;
    if (retryAfterStorage) void send().catch(cleanup);
  };
  const onNotStored = (result: unknown) => {
    const detail = result as { code?: string; chat_id?: string; source_message_id?: string; source_task_id?: string; source_user_message_id?: string };
    if (detail.code !== 'stale_suggested_followup_source' || detail.chat_id !== payload.chat_id ||
        detail.source_message_id !== payload.message_id || detail.source_task_id !== payload.task_id ||
        detail.source_user_message_id !== payload.user_message_id) return;
    if (attempts >= 2) { cleanup(); return; }
    retryAfterStorage = true;
    if (storageConfirmed) void send().catch(cleanup);
  };
  const onStored = (ack: unknown) => {
    const detail = ack as { chat_id?: string; source_message_id?: string; source_task_id?: string };
    if (detail.chat_id === payload.chat_id && detail.source_message_id === payload.message_id && detail.source_task_id === payload.task_id) cleanup();
  };
  const expiry = setTimeout(cleanup, 120_000);
  serviceInstance.addEventListener('aiResponseStorageConfirmed', onStorageConfirmed);
  webSocketService.on('encrypted_suggested_followup_message_not_stored', onNotStored);
  webSocketService.on('encrypted_suggested_followup_message_stored', onStored);
  try { await send(); } catch (error) { cleanup(); throw error; }
}
