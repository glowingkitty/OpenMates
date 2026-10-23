/**
 * Shared predicates for persisted chat draft presentation.
 * Draft-only chats are durable chat shells with an unsent draft but no
 * messages or generated chat metadata. Established chats with a draft must
 * continue to use their normal chat presentation.
 */

import type { Chat } from "../types/chat";

export function isDraftOnlyChatSurface(
  chat: Chat | null | undefined,
  hasLiveDraftContent = false,
): chat is Chat {
  if (!chat || chat.is_hidden_candidate || chat.is_incognito || chat.is_anonymous) {
    return false;
  }

  const hasDraft = Boolean(
    hasLiveDraftContent ||
      chat.encrypted_draft_md ||
      chat.encrypted_draft_preview ||
      (chat.draft_v ?? 0) > 0,
  );
  const hasMessages =
    (chat.messages_v ?? 0) > 0 || (chat.messages?.length ?? 0) > 0;
  const hasGeneratedMetadata = Boolean(
    chat.title ||
      chat.encrypted_title ||
      chat.chat_summary ||
      chat.encrypted_chat_summary ||
      chat.icon ||
      chat.encrypted_icon ||
      chat.category ||
      chat.encrypted_category ||
      (chat.title_v ?? 0) > 0,
  );

  return hasDraft && !hasMessages && !hasGeneratedMetadata && !chat.ideabucket_triggered_at;
}

export function isPersistedDraftOnlyChat(
  chat: Chat | null | undefined,
): chat is Chat {
  return isDraftOnlyChatSurface(chat);
}

/** Keep a pending lookup on its composer, including its first durable draft ID. */
export function isComposerLookupChatCurrent(input: {
  openingChatId: string | null;
  openingDraftChatId: string | null;
  openingLoadGeneration: number;
  currentChat: Chat | null | undefined;
  currentDraftChatId: string | null;
  currentLoadGeneration: number;
}): boolean {
  const currentChatId = input.currentChat?.chat_id ?? null;
  if (currentChatId === input.openingChatId) {
    return !!input.openingChatId || (
      input.currentLoadGeneration === input.openingLoadGeneration &&
      input.currentDraftChatId === input.openingDraftChatId
    );
  }
  // Adoption advances the load generation once; a different reserved ID,
  // established chat or intervening navigation cannot inherit this lookup.
  return !input.openingChatId && !!input.openingDraftChatId
    && currentChatId === input.openingDraftChatId
    && input.currentDraftChatId === input.openingDraftChatId
    && isPersistedDraftOnlyChat(input.currentChat)
    && input.currentLoadGeneration >= input.openingLoadGeneration
    && input.currentLoadGeneration <= input.openingLoadGeneration + 1;
}

/** First-turn send proof independent of welcome/draft presentation transitions. */
export type FirstTurnComposerReason = 'eligible_shell' | 'eligible_draft' | 'unauthenticated' |
  'team' | 'no_chat' | 'draft_mismatch' | 'owner_mismatch' | 'chat_scope' |
  'has_history' | 'not_draft_only';

export function classifyFirstTurnComposerContext(input: {
  chat: Chat | null | undefined;
  temporaryChatId: string | null;
  draftChatId: string | null;
  hasLiveDraftContent: boolean;
  authenticated: boolean;
  accountId: string | null | undefined;
  teamId: string | null;
}): FirstTurnComposerReason {
  if (!input.authenticated || !input.accountId) return 'unauthenticated';
  if (input.teamId) return 'team';
  const chatId = input.chat?.chat_id ?? input.temporaryChatId;
  if (!chatId) return 'no_chat';
  if (chatId !== input.draftChatId) return 'draft_mismatch';
  if (!input.chat) return 'eligible_shell';
  if (input.chat.user_id && input.chat.user_id !== input.accountId) return 'owner_mismatch';
  if (input.chat.team_id || input.chat.is_incognito || input.chat.is_anonymous) return 'chat_scope';
  if ((input.chat.messages_v ?? 0) > 0 || (input.chat.messages?.length ?? 0) > 0) return 'has_history';
  return isDraftOnlyChatSurface(input.chat, input.hasLiveDraftContent)
    ? 'eligible_draft' : 'not_draft_only';
}

/** Reserve one visible shell ID before asynchronous app setup or user focus. */
export function reserveInitialFreshShellId(input: {
  chat: Chat | null | undefined;
  temporaryChatId: string | null;
  selectedChatId: string | null;
  preparedDraftChatId: string | null;
  showWelcome: boolean;
  hasMessages: boolean;
}, createId: () => string): string | null {
  if (input.chat?.chat_id || input.temporaryChatId) return input.temporaryChatId;
  return input.showWelcome && !input.hasMessages && !input.selectedChatId && input.preparedDraftChatId
    ? input.preparedDraftChatId : createId();
}

/** Bind an unclaimed local shell only when no saved chat or other draft owns the editor. */
export function canBindUnclaimedFreshShell(input: {
  chat: Chat | null | undefined;
  temporaryChatId: string | null;
  composerChatId: string;
  draftChatId: string | null;
  activeChatId: string | null;
  pendingDraftSelection: boolean;
  hasMessages: boolean;
  hasLiveDraftContent: boolean;
  showWelcome: boolean;
  authenticated: boolean;
  accountId: string | null | undefined;
  teamId: string | null;
  incognito: boolean;
}): boolean {
  return input.authenticated && !!input.accountId && !input.teamId && !input.incognito &&
    input.showWelcome && !input.chat && !input.activeChatId && !input.hasMessages && !input.hasLiveDraftContent &&
    !input.pendingDraftSelection && input.draftChatId === null &&
    !!input.temporaryChatId && input.composerChatId === input.temporaryChatId;
}

export function isFirstTurnComposerContext(input: Parameters<typeof classifyFirstTurnComposerContext>[0]): boolean {
  const reason = classifyFirstTurnComposerContext(input);
  return reason === 'eligible_shell' || reason === 'eligible_draft';
}

/** A late draft save may activate only the composer that still owns that ID. */
export function canActivatePersistedComposerDraft(input: {
  persistedChatId: string;
  selectedChatId: string | null;
  currentChatId: string | null;
  temporaryChatId: string | null;
  draftChatId: string | null;
}): boolean {
  const owner = input.currentChatId ?? input.temporaryChatId;
  return input.draftChatId === input.persistedChatId &&
    owner === input.persistedChatId &&
    (!input.selectedChatId || input.selectedChatId === input.persistedChatId);
}
