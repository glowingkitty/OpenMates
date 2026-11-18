/*
 * Spawn-kind rules for main chats started by another chat (chat orchestration).
 * A main_chat child is a normal sidebar chat created later by the user's device:
 * no CHATS row is inserted here and no budget is reserved. Only the per-turn
 * descendant limit applies. Sub-chat behaviour is unchanged (default kind).
 */
export const SUB_CHAT_KIND = 'sub_chat';
export const MAIN_CHAT_KIND = 'main_chat';
export const MAIN_CHAT_DESCENDANT_LIMIT = 5;

export function spawnKind(raw, fail) {
  if (raw == null) return SUB_CHAT_KIND;
  if (raw !== SUB_CHAT_KIND && raw !== MAIN_CHAT_KIND) fail(400, 'invalid_spawn_kind');
  return raw;
}

export function isMainChat(kind) {
  return kind === MAIN_CHAT_KIND;
}

/** Roots of a main chat may start from a chat that is itself a main-chat child. */
export function subChatChildFilter() {
  return function filter() {
    this.whereNull('spawn_kind').orWhere('spawn_kind', SUB_CHAT_KIND);
  };
}
