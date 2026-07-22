/**
 * Chat settings usage helpers.
 *
 * Converts local message metadata into display/export rows for the browser-only
 * chat Usage tab. No backend calls are made here; missing values remain visible
 * instead of being silently inferred.
 */

import type { Message } from '../../types/chat';

export interface ChatUsageRow {
  id: string;
  label: string;
  provider: string;
  timestamp: number;
  credits: number | null;
  words: number;
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
