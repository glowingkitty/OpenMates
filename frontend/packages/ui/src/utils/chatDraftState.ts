/**
 * Shared predicates for persisted chat draft presentation.
 * Draft-only chats are durable chat shells with an unsent draft but no
 * messages or generated chat metadata. Established chats with a draft must
 * continue to use their normal chat presentation.
 */

import type { Chat } from "../types/chat";

export function isPersistedDraftOnlyChat(
  chat: Chat | null | undefined,
): chat is Chat {
  if (!chat || chat.is_hidden_candidate || chat.is_incognito || chat.is_anonymous) {
    return false;
  }

  const hasDraft = Boolean(
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
