/** Browser-only timeline reads. No plaintext catalogue or preview is persisted. */
import { get } from 'svelte/store';
import { getApiEndpoint, storageArchiveFetch } from '../config/api';
import { chatDB } from './db';
import { activeTeamId } from '../stores/teamStore';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { fetchAuthenticatedChatMessageWindow, normalizeServerMessage } from './authenticatedChatMessageWindow';
import type { Message } from '../types/chat';
import type { TimelineEntry } from '../utils/chatTimeline';

export type TimelineCursor = { created_at: number; message_id: string };
export type TimelinePage = { chat_id: string; entries: TimelineEntry[]; has_more: boolean; before: TimelineCursor | null };

export async function fetchTimelinePage(chatId: string, shared: boolean, before: TimelineCursor | null, signal: AbortSignal): Promise<TimelinePage> {
  const epoch = getWorkspaceCacheEpoch();
  const team = get(activeTeamId);
  const params = new URLSearchParams();
  if (before) { params.set('before_timestamp', String(before.created_at)); params.set('before_message_id', before.message_id); }
  if (!shared && team) params.set('team_id', team);
  const route = shared ? `/v1/share/chat/${encodeURIComponent(chatId)}/timeline` : `/v1/chats/${encodeURIComponent(chatId)}/timeline`;
  const response = await storageArchiveFetch(getApiEndpoint(`${route}?${params}`), { credentials: 'include', signal });
  if (!response.ok) throw new Error(`Timeline catalogue unavailable (${response.status})`);
  const page = await response.json() as TimelinePage;
  if (signal.aborted || epoch !== getWorkspaceCacheEpoch() || team !== get(activeTeamId)
      || page.chat_id !== chatId || !Array.isArray(page.entries) || page.entries.length > 200
      || page.entries.some(row => !row.message_id || !Number.isFinite(row.created_at) || !['user', 'assistant', 'system'].includes(row.role))) {
    throw new Error('Timeline scope changed');
  }
  if (page.has_more && (!page.before || (before && (page.before.created_at > before.created_at
      || (page.before.created_at === before.created_at && page.before.message_id >= before.message_id))))) {
    throw new Error('Timeline catalogue cursor did not advance');
  }
  return page;
}

export async function fetchTimelineSection(chatId: string, id: string, shared: boolean, responseId?: string | null): Promise<Message[]> {
  const epoch = getWorkspaceCacheEpoch();
  const team = get(activeTeamId);
  const completeSection = async (rows: Message[]): Promise<Message[]> => {
    if (responseId && !rows.some(row => row.message_id === responseId)) {
      // System/permission rows can separate a question from its answer beyond
      // one twenty-message window. Fetch only the identified answer's window.
      const responseRows = await fetchTimelineSection(chatId, responseId, shared);
      const byId = new Map([...rows, ...responseRows].map(row => [row.message_id, row]));
      rows = [...byId.values()].sort((a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id));
    }
    if (epoch !== getWorkspaceCacheEpoch() || team !== get(activeTeamId)) throw new Error('Timeline scope changed');
    return rows;
  };
  if (!shared) {
    const result = await fetchAuthenticatedChatMessageWindow(chatId, { direction: 'around', anchorMessageId: id,
      includeCanonicalMessages: true, respectCompressionBoundary: false });
    if (!result.anchorFound || !result.canonicalMessages?.some(row => row.message_id === id)) throw new Error('Timeline target unavailable');
    return completeSection(result.canonicalMessages);
  }
  const response = await storageArchiveFetch(getApiEndpoint(`/v1/share/chat/${encodeURIComponent(chatId)}/section/${encodeURIComponent(id)}`));
  if (!response.ok) throw new Error('Shared timeline section unavailable');
  const payload = await response.json() as { chat_id: string; messages: Array<Record<string, unknown>>; anchor_found: boolean;
    oversized_message_cursor?: { message_id: string } | null };
  if (epoch !== getWorkspaceCacheEpoch() || team !== get(activeTeamId) || payload.chat_id !== chatId || !payload.anchor_found) throw new Error('Timeline scope changed');
  if (payload.oversized_message_cursor) {
    const selectedId = payload.oversized_message_cursor.message_id;
    const exactResponse = await storageArchiveFetch(getApiEndpoint(`/v1/share/chat/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(selectedId)}`));
    if (!exactResponse.ok) throw new Error('Shared timeline target unavailable');
    const exact = await exactResponse.json() as { message?: Record<string, unknown> };
    if (!exact.message || normalizeServerMessage(exact.message, chatId)?.message_id !== selectedId) throw new Error('Timeline target identity changed');
    payload.messages.push(exact.message);
  }
  const rows = payload.messages.map(raw => normalizeServerMessage(raw, chatId));
  if (rows.length > 20 || rows.some(row => !row) || !rows.some(row => row?.message_id === id)) throw new Error('Timeline target unavailable');
  if (epoch !== getWorkspaceCacheEpoch() || team !== get(activeTeamId)) throw new Error('Timeline scope changed');
  const messages = await Promise.all(rows.map(row => chatDB.decryptMessageFields(row!, chatId)));
  if (epoch !== getWorkspaceCacheEpoch() || team !== get(activeTeamId)) throw new Error('Timeline scope changed');
  return completeSection(messages);
}
