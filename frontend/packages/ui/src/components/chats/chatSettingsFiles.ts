/**
 * Chat settings downloadable file helpers.
 *
 * Extracts embed references from local chat messages and resolves only entries
 * that have an existing client-side download/export path. This keeps the Files
 * tab deterministic and avoids listing generic result cards as files.
 */

import type { Message } from '../../types/chat';
import { embedStore, type UploadedFileSearchResult } from '../../services/embedStore';

const DOWNLOADABLE_TYPES = new Set(['pdf', 'image', 'code', 'audio', 'recording', 'docs', 'sheets', 'design']);

export interface ChatFileRow extends UploadedFileSearchResult {
  metadata: string;
}

export function extractChatEmbedRefs(messages: Message[]): string[] {
  const refs = new Set<string>();
  for (const message of messages) {
    const text = `${message.content ?? ''}\n${message.truncated_content ?? ''}`;
    for (const match of text.matchAll(/embed:[a-zA-Z0-9_:-]+/g)) {
      refs.add(match[0]);
    }
  }
  return [...refs];
}

function isDownloadable(file: UploadedFileSearchResult): boolean {
  const type = String(file.type ?? '').toLowerCase();
  const nodeType = String(file.nodeType ?? '').toLowerCase();
  return DOWNLOADABLE_TYPES.has(type) || DOWNLOADABLE_TYPES.has(nodeType);
}

function buildMetadata(file: UploadedFileSearchResult): string {
  return file.subtitle || file.type || 'File';
}

export async function loadChatFileRows(messages: Message[]): Promise<ChatFileRow[]> {
  const refs = extractChatEmbedRefs(messages);
  if (refs.length === 0) return [];
  const files = await embedStore.getUploadedFilesByContentRefs(refs);
  return files
    .filter(isDownloadable)
    .map((file) => ({ ...file, metadata: buildMetadata(file) }));
}
