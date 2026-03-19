/**
 * draftAudioChatStore.ts
 *
 * Tracks chat IDs that were pre-allocated for audio recordings made in a new (not yet sent) chat.
 *
 * When a user records audio before sending their first message, we pre-allocate a UUID so the
 * transcription usage entry can be linked to a chat. If the user subsequently sends the message,
 * the UUID becomes a real chat and the usage entry resolves normally. If the user never sends,
 * the UUID never appears in the chats collection — the usage entry will have is_deleted=true in
 * the daily overview. This store lets SettingsUsage distinguish "unsent draft recording" from a
 * genuinely deleted chat, so it can show the appropriate label and icon.
 *
 * Storage: localStorage — persists across page refreshes, cleared per-key when a chat is sent.
 * No encryption needed: these are just UUIDs with no sensitive content.
 *
 * Key: DRAFT_AUDIO_CHAT_KEY_PREFIX + chat_id
 * Value: timestamp (ISO string) of when the recording was made — for potential future cleanup.
 */

const DRAFT_AUDIO_STORAGE_PREFIX = "om_draft_audio_chat:";

/**
 * Mark a chat_id as a "draft audio" chat — created for an audio recording that has not yet
 * been sent as part of a chat message.
 */
export function markChatIdAsDraftAudio(chatId: string): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(
      DRAFT_AUDIO_STORAGE_PREFIX + chatId,
      new Date().toISOString(),
    );
  } catch (e) {
    console.warn(
      "[DraftAudioChatStore] Failed to persist draft audio chat id:",
      e,
    );
  }
}

/**
 * Remove a chat_id from the draft-audio set. Call this when the chat has been sent
 * (i.e., the user pressed Send) so the usage entry is no longer treated as an unsent draft.
 */
export function unmarkChatIdAsDraftAudio(chatId: string): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.removeItem(DRAFT_AUDIO_STORAGE_PREFIX + chatId);
  } catch (e) {
    console.warn(
      "[DraftAudioChatStore] Failed to remove draft audio chat id:",
      e,
    );
  }
}

/**
 * Returns true if the given chat_id was pre-allocated for an audio recording that has
 * not yet been sent as a chat message.
 */
function isChatIdDraftAudio(chatId: string): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    return localStorage.getItem(DRAFT_AUDIO_STORAGE_PREFIX + chatId) !== null;
  } catch {
    return false;
  }
}

/**
 * Returns all currently-tracked draft audio chat IDs (as a Set for O(1) lookup).
 */
export function getAllDraftAudioChatIds(): Set<string> {
  const result = new Set<string>();
  if (typeof localStorage === "undefined") return result;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(DRAFT_AUDIO_STORAGE_PREFIX)) {
        result.add(key.slice(DRAFT_AUDIO_STORAGE_PREFIX.length));
      }
    }
  } catch {
    // Storage read error — return empty set
  }
  return result;
}
