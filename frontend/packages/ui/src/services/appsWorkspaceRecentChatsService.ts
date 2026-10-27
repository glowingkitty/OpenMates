import { chatDB } from './db';
import { chatMetadataCache } from './chatMetadataCache';
import { get } from 'svelte/store';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { activeTeamContext } from '../stores/teamStore';
import type { Chat } from '../types/chat';

/** A bounded client-side fallback for app Focus chats that produced no embeds. */
export async function loadAppsRecentChats(appId: string, teamId?: string): Promise<Chat[]> {
  const owner = get(userProfile).user_id;
  const team = get(activeTeamContext);
  if (!get(authStore).isAuthenticated || !owner || (team.teamId ?? undefined) !== teamId) return [];
  const current = () => get(authStore).isAuthenticated && get(userProfile).user_id === owner
    && get(activeTeamContext).epoch === team.epoch && (get(activeTeamContext).teamId ?? undefined) === teamId;
  const chats = await chatDB.getAllChats(undefined, { limit: 60 });
  if (!current()) return [];
  const related: Chat[] = [];
  for (const chat of chats) {
    if ((chat.team_id ?? undefined) !== teamId || chat.chat_id.startsWith('demo-') || chat.chat_id.startsWith('example-')) continue;
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (!current()) return [];
    if (metadata?.activeFocusId?.startsWith(appId + '-')) related.push({
      ...chat, title: metadata.title, chat_summary: metadata.summary, icon: metadata.icon, category: metadata.category,
    });
    if (related.length >= 12) break;
  }
  return related;
}
