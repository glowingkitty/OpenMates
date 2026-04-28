// frontend/packages/ui/src/services/chatSyncMerge.ts
// Pure helpers for merging server chat metadata with local IndexedDB state.
// Keeps phased-sync policy testable without importing websocket/database services.
// The most important invariant is key/content consistency: encrypted fields and
// messages preserved from local storage must never be paired with a different
// server-provided encrypted_chat_key.

import type { Chat } from "../types/chat";

const MAX_CANDIDATE_KEYS = 5;

export function hasEncryptedChatKeyMismatch(
  serverChat: Partial<Chat> & { id: string },
  localChat: Chat | null,
): boolean {
  return Boolean(
    serverChat.encrypted_chat_key &&
      localChat?.encrypted_chat_key &&
      serverChat.encrypted_chat_key !== localChat.encrypted_chat_key,
  );
}

function appendCandidateKey(
  existing: string[] | null | undefined,
  encryptedKey: string | null | undefined,
): string[] | null | undefined {
  if (!encryptedKey) return existing;
  const candidates = existing ?? [];
  if (candidates.includes(encryptedKey)) return candidates;
  return [...candidates, encryptedKey].slice(-MAX_CANDIDATE_KEYS);
}

/**
 * Merge server chat data with local data, preserving higher local versions only
 * when the local ciphertext is decryptable with the merged chat key.
 */
export async function mergeServerChatWithLocal(
  serverChat: Partial<Chat> & { id: string },
  localChat: Chat | null,
  currentUserId?: string,
): Promise<Chat> {
  const nowTimestamp = Math.floor(Date.now() / 1000);

  if (!localChat) {
    return {
      chat_id: serverChat.id,
      encrypted_title: serverChat.encrypted_title ?? null,
      messages_v: serverChat.messages_v ?? 0,
      title_v: serverChat.title_v ?? 0,
      draft_v: serverChat.draft_v ?? 0,
      unread_count: serverChat.unread_count ?? 0,
      created_at: serverChat.created_at ?? nowTimestamp,
      updated_at: serverChat.updated_at ?? nowTimestamp,
      last_edited_overall_timestamp:
        serverChat.last_edited_overall_timestamp ??
        serverChat.updated_at ??
        nowTimestamp,
      encrypted_draft_md: serverChat.encrypted_draft_md,
      encrypted_draft_preview: serverChat.encrypted_draft_preview,
      encrypted_chat_key: serverChat.encrypted_chat_key,
      candidate_encrypted_keys: serverChat.candidate_encrypted_keys,
      encrypted_icon: serverChat.encrypted_icon,
      encrypted_category: serverChat.encrypted_category,
      last_visible_message_id: serverChat.last_visible_message_id,
      pinned: serverChat.pinned,
      encrypted_follow_up_request_suggestions:
        serverChat.encrypted_follow_up_request_suggestions,
      encrypted_chat_summary: serverChat.encrypted_chat_summary,
      encrypted_chat_tags: serverChat.encrypted_chat_tags,
      encrypted_top_recommended_apps_for_chat:
        serverChat.encrypted_top_recommended_apps_for_chat,
      encrypted_active_focus_id: serverChat.encrypted_active_focus_id,
      is_shared: serverChat.is_shared,
      is_private: serverChat.is_private,
      user_id: currentUserId,
    };
  }

  const keyMismatch = hasEncryptedChatKeyMismatch(serverChat, localChat);
  const merged: Chat = {
    chat_id: serverChat.id,
    user_id: localChat.user_id ?? currentUserId,
    encrypted_title:
      serverChat.encrypted_title ?? localChat.encrypted_title ?? null,
    messages_v: serverChat.messages_v ?? localChat.messages_v ?? 0,
    title_v: serverChat.title_v ?? localChat.title_v ?? 0,
    draft_v: serverChat.draft_v ?? localChat.draft_v ?? 0,
    unread_count: serverChat.unread_count ?? localChat.unread_count ?? 0,
    created_at: serverChat.created_at ?? localChat.created_at ?? nowTimestamp,
    updated_at: serverChat.updated_at ?? localChat.updated_at ?? nowTimestamp,
    last_edited_overall_timestamp:
      serverChat.last_edited_overall_timestamp ??
      localChat.last_edited_overall_timestamp ??
      serverChat.updated_at ??
      localChat.updated_at ??
      serverChat.created_at ??
      localChat.created_at ??
      nowTimestamp,
    encrypted_draft_md:
      serverChat.encrypted_draft_md ?? (keyMismatch ? undefined : localChat.encrypted_draft_md),
    encrypted_draft_preview:
      serverChat.encrypted_draft_preview ??
      (keyMismatch ? undefined : localChat.encrypted_draft_preview),
    encrypted_chat_key:
      serverChat.encrypted_chat_key ?? localChat.encrypted_chat_key,
    candidate_encrypted_keys:
      serverChat.candidate_encrypted_keys ?? localChat.candidate_encrypted_keys,
    encrypted_icon: serverChat.encrypted_icon ?? localChat.encrypted_icon,
    encrypted_category:
      serverChat.encrypted_category ?? localChat.encrypted_category,
    last_visible_message_id:
      serverChat.last_visible_message_id ?? localChat.last_visible_message_id,
    pinned: serverChat.pinned ?? localChat.pinned,
    encrypted_follow_up_request_suggestions:
      serverChat.encrypted_follow_up_request_suggestions ??
      localChat.encrypted_follow_up_request_suggestions,
    encrypted_chat_summary:
      serverChat.encrypted_chat_summary ?? localChat.encrypted_chat_summary,
    encrypted_chat_tags:
      serverChat.encrypted_chat_tags ?? localChat.encrypted_chat_tags,
    encrypted_top_recommended_apps_for_chat:
      serverChat.encrypted_top_recommended_apps_for_chat ??
      localChat.encrypted_top_recommended_apps_for_chat,
    encrypted_active_focus_id:
      serverChat.encrypted_active_focus_id ?? localChat.encrypted_active_focus_id,
    is_shared: serverChat.is_shared ?? localChat.is_shared,
    is_private: serverChat.is_private ?? localChat.is_private,
  };

  if (keyMismatch) {
    merged.candidate_encrypted_keys = appendCandidateKey(
      merged.candidate_encrypted_keys,
      localChat.encrypted_chat_key,
    );
    merged.messages_v = 0;
    return merged;
  }

  const localTitleV = localChat.title_v || 0;
  const serverTitleV = serverChat.title_v || 0;
  if (localTitleV >= serverTitleV && localChat.encrypted_title) {
    merged.encrypted_title = localChat.encrypted_title;
    merged.title_v = localChat.title_v;
  }

  const localDraftV = localChat.draft_v || 0;
  const serverDraftV = serverChat.draft_v || 0;
  if (localDraftV >= serverDraftV) {
    if (localChat.encrypted_draft_md) {
      merged.encrypted_draft_md = localChat.encrypted_draft_md;
    }
    if (localChat.encrypted_draft_preview) {
      merged.encrypted_draft_preview = localChat.encrypted_draft_preview;
    }
    merged.draft_v = localChat.draft_v;
  }

  const localMessagesV = localChat.messages_v || 0;
  const serverMessagesV = serverChat.messages_v || 0;
  if (localMessagesV > serverMessagesV) {
    merged.messages_v = localChat.messages_v;
  }

  return merged;
}
