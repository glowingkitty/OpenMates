/**
 * Chat settings downloadable file helpers.
 *
 * Extracts embed references from local chat messages and resolves only entries
 * that have an existing client-side download/export path. This keeps the Files
 * tab deterministic and avoids listing generic result cards as files.
 */

import type { Message } from '../../types/chat';
import { embedStore, type UploadedFileSearchResult } from '../../services/embedStore';
import { getStaticGeneratedAudioDownload } from '../../services/generatedAudioExport';

const DOWNLOADABLE_TYPES = new Set([
  'audio',
  'audio-recording',
  'code',
  'code-code',
  'design',
  'docs',
  'docs-doc',
  'image',
  'images-image',
  'pdf',
  'recording',
  'sheets',
  'sheets-sheet',
  'spreadsheet',
]);
const JSON_EMBED_BLOCK_RE = /```json\s*([\s\S]*?)\s*```/g;
const INLINE_EMBED_REF_RE = /embed:[a-zA-Z0-9_:-]+/g;

export interface ChatFileRow extends UploadedFileSearchResult {
  metadata: string;
}

export function extractChatEmbedRefs(messages: Message[]): string[] {
  const refs = new Set<string>();
  for (const message of messages) {
    const text = `${message.content ?? ''}\n${message.truncated_content ?? ''}`;
    for (const match of Array.from(text.matchAll(INLINE_EMBED_REF_RE))) {
      refs.add(match[0]);
    }
    for (const match of Array.from(text.matchAll(JSON_EMBED_BLOCK_RE))) {
      const ref = parseJsonEmbedRef(match[1]);
      if (ref) refs.add(ref);
    }
  }
  return Array.from(refs.values());
}

function parseJsonEmbedRef(json: string): string | null {
  try {
    const parsed = JSON.parse(json.trim()) as { embed_id?: unknown };
    return typeof parsed.embed_id === 'string' && parsed.embed_id.trim()
      ? `embed:${parsed.embed_id.trim().replace(/^embed:/, '')}`
      : null;
  } catch {
    return null;
  }
}

function parseJsonEmbed(json: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(json.trim());
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

export function hasStaticGeneratedAudioEmbedRefs(messages: Message[]): boolean {
  for (const message of messages) {
    const text = `${message.content ?? ''}\n${message.truncated_content ?? ''}`;
    for (const match of Array.from(text.matchAll(JSON_EMBED_BLOCK_RE))) {
      const parsed = parseJsonEmbed(match[1]);
      if (
        parsed?.type === 'app_skill_use' &&
        parsed.app_id === 'audio' &&
        (parsed.skill_id === 'generate' || parsed.skill_id === 'speak')
      ) {
        return true;
      }
    }
  }
  return false;
}

function isDownloadable(file: UploadedFileSearchResult): boolean {
  const type = String(file.type ?? '').toLowerCase();
  const nodeType = String(file.nodeType ?? '').toLowerCase();
  if (type === 'web' || type.startsWith('web-')) return false;
  return DOWNLOADABLE_TYPES.has(type) || DOWNLOADABLE_TYPES.has(nodeType);
}

function buildMetadata(file: UploadedFileSearchResult): string {
  return file.subtitle || file.type || 'File';
}

async function loadStaticGeneratedAudioRow(contentRef: string): Promise<ChatFileRow | null> {
  const embed = await embedStore.get(contentRef);
  if (!embed || typeof embed !== 'object') return null;
  const content = typeof embed.content === 'string' ? embed.content : embed;
  const download = getStaticGeneratedAudioDownload(content);
  if (!download) return null;
  const embedId = contentRef.replace(/^embed:/, '');
  return {
    embedId,
    contentRef,
    title: download.filename,
    subtitle: 'Audio',
    type: 'audio',
    nodeType: 'recording',
    iconName: 'audio',
    createdAt: 0,
    updatedAt: 0,
    metadata: 'Audio',
  };
}

export async function loadChatFileRows(messages: Message[]): Promise<ChatFileRow[]> {
  const refs = extractChatEmbedRefs(messages);
  if (refs.length === 0) return [];
  const files = await embedStore.getUploadedFilesByContentRefs(refs);
  const rows = files
    .filter(isDownloadable)
    .map((file) => ({ ...file, metadata: buildMetadata(file) }));
  const listedRefs = new Set(rows.map((row) => row.contentRef));
  for (const ref of refs) {
    if (listedRefs.has(ref)) continue;
    const staticAudioRow = await loadStaticGeneratedAudioRow(ref);
    if (!staticAudioRow) continue;
    rows.push(staticAudioRow);
    listedRefs.add(ref);
  }
  return rows;
}
