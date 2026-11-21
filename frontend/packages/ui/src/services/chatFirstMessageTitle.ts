/**
 * Loads the first-message display title for a chat that has no generated title
 * yet (rule: `utils/chatDisplayTitle.ts`). Messages come from the local
 * IndexedDB copy, which `chatDB` decrypts client-side with the chat key; the
 * result is held in memory only and never persisted or sent to the server.
 * Entries are keyed by the account/team workspace identity, so a logout,
 * account switch or team switch never serves another identity's text.
 */
import { chatDB } from './db';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { firstMessageDisplayTitle } from '../utils/chatDisplayTitle';

const MAX_ENTRIES = 256;
const firstMessageTitles = new Map<string, string>();

/** The first user message's readable beginning, or null when the chat has none. */
export async function loadFirstMessageDisplayTitle(chatId: string): Promise<string | null> {
    const key = `${getWorkspaceCacheIdentity() ?? 'guest'}|${chatId}`;
    const known = firstMessageTitles.get(key);
    if (known) return known;
    const title = firstMessageDisplayTitle(await chatDB.getMessagesForChat(chatId));
    if (!title) return null;
    if (firstMessageTitles.size >= MAX_ENTRIES) firstMessageTitles.clear();
    firstMessageTitles.set(key, title);
    return title;
}
