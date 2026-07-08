// frontend/packages/ui/src/services/anonymousChatIds.ts
// Shared anonymous chat ID helpers.
// Anonymous chats are session-local, logged-out chats stored in IndexedDB with
// keys wrapped by the anonymous session key instead of an account master key.
// Keep this module dependency-free so database guards can use it without
// importing the anonymous storage facade and creating service cycles.

export const ANONYMOUS_CHAT_PREFIX = "anonymous-";

export function isAnonymousChatId(chatId: string | null | undefined): chatId is string {
  return Boolean(chatId?.startsWith(ANONYMOUS_CHAT_PREFIX));
}
