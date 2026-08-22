/**
 * Chat settings usage helpers.
 *
 * Converts local message metadata into display/export rows for the browser-only
 * chat Usage tab. No backend calls are made here; missing values remain visible
 * instead of being silently inferred.
 */

import type { ChatUsageEntry, Message } from '../../types/chat';
import { apiEndpoints, getApiEndpoint } from '../../config/api';

export interface ChatUsageRow {
  id: string;
  label: string;
  provider: string;
  timestamp: number;
  credits: number | null;
  words: number;
  iconName?: string;
  appId?: string | null;
  skillId?: string | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
}

export function buildChatUsageRows(messages: Message[]): ChatUsageRow[] {
  return messages
    .filter((message) => message.role === 'assistant')
    .map((message, index) => {
      const content = message.content ?? message.truncated_content ?? '';
      return {
        id: message.message_id || `usage-${index}`,
        label: message.model_name ? 'AI | Ask' : 'AI | Ask',
        provider: message.model_name ?? 'Unknown provider',
        timestamp: message.created_at,
        credits: typeof message.example_response_credits === 'number' ? message.example_response_credits : null,
        words: content.trim() ? content.trim().split(/\s+/).length : 0,
      };
    });
}

export async function loadChatUsageRows(chatId: string, limit = 500): Promise<ChatUsageRow[]> {
  const url = new URL(getApiEndpoint(apiEndpoints.usage.getChatEntries));
  url.searchParams.set('chat_id', chatId);
  url.searchParams.set('limit', String(limit));

  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const detail = errorData.detail || errorData.message || response.statusText;
    throw new Error(`Failed to load chat usage entries: ${response.status} ${detail}`);
  }

  const data = await response.json();
  if (!data || typeof data !== 'object' || !Array.isArray(data.entries)) {
    throw new Error('Invalid chat usage entries response');
  }
  return usageEntriesToChatUsageRows(data.entries as ChatUsageEntry[]);
}

export async function loadChatUsageTotal(chatId: string): Promise<number> {
  const url = new URL(getApiEndpoint(apiEndpoints.usage.chatTotal));
  url.searchParams.set('chat_id', chatId);

  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const detail = errorData.detail || errorData.message || response.statusText;
    throw new Error(`Failed to load chat usage total: ${response.status} ${detail}`);
  }

  const data = await response.json();
  const total = Number(data?.total_credits);
  if (!Number.isFinite(total)) throw new Error('Invalid chat usage total response');
  return total;
}

export function usageEntriesToChatUsageRows(entries: ChatUsageEntry[]): ChatUsageRow[] {
  return entries.map((entry) => ({
    id: entry.id || entry.message_id || `usage-${normalizeTimestamp(entry.created_at)}`,
    label: labelForUsageEntry(entry),
    provider: providerForUsageEntry(entry),
    timestamp: normalizeTimestamp(entry.created_at),
    credits: typeof entry.credits === 'number' ? entry.credits : null,
    words: 0,
    iconName: iconForUsageEntry(entry),
    appId: entry.app_id ?? null,
    skillId: entry.skill_id ?? null,
    inputTokens: typeof entry.input_tokens === 'number' ? entry.input_tokens : null,
    outputTokens: typeof entry.output_tokens === 'number' ? entry.output_tokens : null,
  }));
}

function labelForUsageEntry(entry: ChatUsageEntry): string {
  if (entry.app_id && entry.skill_id) return `${entry.app_id} | ${entry.skill_id}`;
  if (entry.app_id) return entry.app_id;
  return entry.type || 'Unknown activity';
}

function providerForUsageEntry(entry: ChatUsageEntry): string {
  const providerParts = [entry.server_provider, entry.server_region].filter(Boolean);
  if (providerParts.length > 0) return providerParts.join(' / ');
  return entry.model_used || 'Unknown provider';
}

function iconForUsageEntry(entry: ChatUsageEntry): string {
  const appIconMap: Record<string, string> = {
    web: 'web',
    ai: 'ai',
    news: 'news',
    videos: 'videos',
    maps: 'maps',
    code: 'code',
    audio: 'audio',
  };
  return entry.app_id ? appIconMap[entry.app_id] || 'chat' : 'chat';
}

function normalizeTimestamp(timestamp: number | string): number {
  if (typeof timestamp === 'number') return timestamp;
  const parsed = Date.parse(timestamp);
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : 0;
}

export function totalKnownCredits(rows: ChatUsageRow[]): number {
  return rows.reduce((sum, row) => sum + (row.credits ?? 0), 0);
}

export function usageRowsToCsv(rows: ChatUsageRow[]): string {
  const header = ['id', 'label', 'provider', 'timestamp', 'credits', 'words'];
  const body = rows.map((row) => [row.id, row.label, row.provider, String(row.timestamp), row.credits ?? '', row.words]
    .map((value) => `"${String(value).replace(/"/g, '""')}"`)
    .join(','));
  return [header.join(','), ...body].join('\n');
}

export function usageRowsToYaml(rows: ChatUsageRow[]): string {
  return rows.map((row) => [
    `- id: ${row.id}`,
    `  label: ${row.label}`,
    `  provider: ${row.provider}`,
    `  timestamp: ${row.timestamp}`,
    `  credits: ${row.credits ?? 'unknown'}`,
    `  words: ${row.words}`,
  ].join('\n')).join('\n');
}
