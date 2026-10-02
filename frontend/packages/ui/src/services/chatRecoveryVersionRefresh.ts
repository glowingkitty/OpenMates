/** Read the persisted version after a completion's optimistic-version conflict. */
import { getApiEndpoint } from "../config/api";
import type { Chat } from "../types/chat";

export async function refreshRecoveryChatVersion(chat: Chat): Promise<Chat | null> {
  const query = new URLSearchParams({ limit: "1", respect_compression_boundary: "false" });
  if (chat.team_id) query.set("team_id", chat.team_id);
  try {
    // The existing first-party window route authorizes this owner/Team and reads
    // Directus metadata. A local optimistic version can be ahead of persistence;
    // waiting only for a larger local version cannot repair that conflict.
    const response = await fetch(getApiEndpoint(`/v1/chats/${encodeURIComponent(chat.chat_id)}/messages/window?${query}`), {
      credentials: "include", cache: "no-store", signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return null;
    const result = await response.json();
    if (result.chat_id !== chat.chat_id || !Number.isSafeInteger(result.messages_v) || result.messages_v < 0) return null;
    return { ...chat, messages_v: result.messages_v };
  } catch { return null; }
}
