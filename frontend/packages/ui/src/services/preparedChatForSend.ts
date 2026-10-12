/** A tab-local, invisible new-chat shell reserved before the user presses Send. */
import { get } from "svelte/store";
import { authStore } from "../stores/authStore";
import { userProfile } from "../stores/userProfile";
import { getActiveTeamContextSnapshot } from "../stores/teamStore";
import { incognitoMode } from "../stores/incognitoModeStore";
import { draftEditorUIState } from "./drafts/draftState";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { chatDB } from "./db";
import { getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { isPublicChat } from "../demo_chats/convertToChat";
import type { Chat } from "../types/chat";

interface PreparedChat {
  scope: string;
  accountId: string;
  teamEpoch: number;
  chatId: string;
  shell: Chat;
  ready: Promise<void>;
}

let prepared: PreparedChat | null = null;

function currentScope(): { scope: string; accountId: string; teamEpoch: number } | null {
  const team = getActiveTeamContextSnapshot();
  const scope = getWorkspaceCacheIdentity();
  const accountId = get(userProfile).user_id;
  if (!get(authStore).isAuthenticated || !scope || !accountId || team.teamId || incognitoMode.get()) return null;
  return { scope, accountId, teamEpoch: team.epoch };
}

function matchesScope(entry: PreparedChat, scope: NonNullable<ReturnType<typeof currentScope>>): boolean {
  return entry.scope === scope.scope && entry.accountId === scope.accountId && entry.teamEpoch === scope.teamEpoch;
}

/**
 * Idempotent and safe to call on composer focus or microphone activation. It
 * reserves an ID synchronously, then primes the key without putting an empty
 * chat in the visible list. A draft save and a racing Send reuse the same ID.
 */
export function prepareChatForSend(input: {
  currentChatId?: string | null;
  draftChatId?: string | null;
} = {}): void {
  const scope = currentScope();
  if (!scope || input.currentChatId || (input.draftChatId && isPublicChat(input.draftChatId))) {
    prepared = null;
    return;
  }
  const draftId = input.draftChatId ?? get(draftEditorUIState).currentChatId;
  if (prepared && matchesScope(prepared, scope) && (!draftId || prepared.chatId === draftId)) return;
  // Resolve the encrypted account-directory presence once while the composer
  // is idle. The metadata lookup carries no draft and never gates focus.
  void import("./chatSyncService").then(({ chatSyncService }) =>
    chatSyncService.beginEmptyConnectedAccountLookup(),
  ).catch((error) => console.warn("[PreparedChatForSend] Account inventory warmup failed", error));
  const chatId = draftId || crypto.randomUUID();
  const now = Math.floor(Date.now() / 1000);
  const shell: Chat = {
    chat_id: chatId, team_id: null, encrypted_title: null,
    unread_count: 0, messages_v: 0, title_v: 0, draft_v: 0,
    created_at: now, updated_at: now, last_edited_overall_timestamp: now,
  };
  const entry: PreparedChat = { ...scope, chatId, shell, ready: Promise.resolve() };
  prepared = entry;
  if (!draftId) {
    draftEditorUIState.update((state) => state.currentChatId
      ? state : { ...state, currentChatId: chatId });
  }
  entry.ready = (async () => {
    // A saved draft may have this ID already. Never generate a replacement key
    // for a chat whose ciphertext belongs to another key or account.
    const existing = await chatDB.getRawChat(chatId);
    if (existing) {
      if ((existing.team_id ?? null) !== null) return;
      if (existing.encrypted_chat_key) await chatKeyManager.getKey(chatId);
      return;
    }
    if (prepared !== entry || !matchesScope(entry, currentScope() ?? { scope: "", accountId: "", teamEpoch: -1 })) return;
    chatKeyManager.createKeyForNewChat(chatId);
  })();
  void entry.ready.catch((error) => {
    if (prepared === entry) prepared = null;
    console.warn("[PreparedChatForSend] Could not prime chat key", error);
  });
}

/** Read only the shell for the exact current owner and composer draft. */
export function getPreparedChatForSend(chatId: string): { shell: Chat; ready: Promise<void> } | null {
  const scope = currentScope();
  const entry = prepared;
  if (!entry || !scope || !matchesScope(entry, scope) || entry.chatId !== chatId) return null;
  return { shell: entry.shell, ready: entry.ready };
}

export function forgetPreparedChatForSend(chatId: string): void {
  if (prepared?.chatId === chatId) prepared = null;
}
