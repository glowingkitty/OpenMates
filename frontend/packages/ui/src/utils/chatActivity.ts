// Groups concurrent work beneath the nearest available top-level parent.
// Chat IDs come from lifecycle state; ancestry comes from encrypted local sync.
// Hidden parents stay private and cycles cannot trap navigation.
// Count one sidebar entry per parent, with each active descendant once.
// The function is pure so every supported client can share these semantics.
export interface ChatActivityRecord { chat_id: string; parent_id?: string | null; is_hidden?: boolean; is_hidden_candidate?: boolean }

export interface RunningChatGroup<T extends ChatActivityRecord = ChatActivityRecord> {
  chat: T;
  activeSubChatCount: number;
}

/** Every visible processing ancestor needs an indicator, even when not the root. */
export function processingAncestorIds<T extends ChatActivityRecord>(chats: T[], runningIds: ReadonlySet<string>): Set<string> {
  const byId = new Map(chats.map(chat => [chat.chat_id, chat]));
  const result = new Set<string>();
  for (const id of runningIds) {
    const ancestry: T[] = [];
    const visited = new Set<string>();
    let chat = byId.get(id);
    while (chat && !visited.has(chat.chat_id)) {
      visited.add(chat.chat_id); ancestry.push(chat); chat = chat.parent_id ? byId.get(chat.parent_id) : undefined;
    }
    if (ancestry.some(chat => chat.is_hidden || chat.is_hidden_candidate)) continue;
    for (const ancestor of ancestry) result.add(ancestor.chat_id);
  }
  return result;
}

/** Count each running conversation once, and present it under its available root. */
export function aggregateRunningChats<T extends ChatActivityRecord>(chats: T[], runningIds: ReadonlySet<string>): RunningChatGroup<T>[] {
  const byId = new Map(chats.map(chat => [chat.chat_id, chat]));
  const groups = new Map<string, RunningChatGroup<T>>();
  for (const id of runningIds) {
    let root = byId.get(id);
    if (!root) continue;
    const visited = new Set([id]);
    let hidden = root.is_hidden || root.is_hidden_candidate;
    while (root.parent_id && byId.has(root.parent_id) && !visited.has(root.parent_id)) {
      visited.add(root.parent_id);
      root = byId.get(root.parent_id)!;
      hidden ||= root.is_hidden || root.is_hidden_candidate;
    }
    if (hidden) continue;
    let group = groups.get(root.chat_id);
    if (!group) {
      group = { chat: root, activeSubChatCount: 0 };
      groups.set(root.chat_id, group);
    }
    if (id !== root.chat_id) group.activeSubChatCount += 1;
  }
  return [...groups.values()];
}
