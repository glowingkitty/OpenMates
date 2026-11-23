/**
 * Chat settings downloadable file helpers.
 *
 * Extracts embed references from local chat messages and resolves only entries
 * that have an existing client-side download/export path. This keeps the Files
 * tab deterministic and avoids listing generic result cards as files.
 */

import type { Message } from '../../types/chat';
import { embedStore, type UploadedFileSearchResult } from '../../services/embedStore';
import { decodeToonContent } from '../../services/embedResolver';
import { hasMediaEncryptionMetadata } from '../../services/encryption/mediaEncryption';
import { normalizeEmbedType } from '../../data/embedRegistry.generated';
import { EMBROIDERY_FORMATS, readEmbroideryDesign } from '../embeds/design/embroideryDesign';
import { readEmbroideryFile } from '../embeds/design/embroideryDownload';
import { extractEmbedIdsFromContent, getEmbedFileReferences, type ChatFileReference } from '../../demo_chats/exampleChatFiles';

const DOWNLOADABLE_TYPES = new Set([
  'audio',
  'audio-recording',
  'code',
  'code-code',
  'design',
  'document',
  'docs',
  'docs-doc',
  'image',
  'images-image',
  'model3d',
  'music',
  'notebook',
  'pdf',
  'remotion-video',
  'recording',
  'sheet',
  'sheets',
  'sheets-sheet',
  'spreadsheet',
  'video',
]);
const JSON_EMBED_BLOCK_RE = /```json\s*([\s\S]*?)\s*```/g;
const INLINE_EMBED_REF_RE = /embed:[a-zA-Z0-9_.:-]+/g;

export interface ChatFileRow {
  embedId: string;
  contentRef: string;
  title: string;
  subtitle: string;
  type: string;
  nodeType: string;
  iconName: string;
  createdAt: number;
  updatedAt: number;
  metadata: string;
  appId?: string | null;
  skillId?: string | null;
  url?: string | null;
  mimeType?: string | null;
  readBlob?: () => Promise<Blob>;
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

function isDownloadable(file: UploadedFileSearchResult): boolean {
  const type = String(file.type ?? '').toLowerCase();
  const nodeType = String(file.nodeType ?? '').toLowerCase();
  if (type === 'web' || type.startsWith('web-')) return false;
  if (normalizeEmbedType(type) === 'design-embroidery') return false;
  return DOWNLOADABLE_TYPES.has(type) || DOWNLOADABLE_TYPES.has(nodeType);
}

function buildMetadata(file: UploadedFileSearchResult): string {
  return file.subtitle || file.type || 'File';
}

function normalizeStaticRow(row: ChatFileReference): ChatFileRow {
  return { ...row };
}

async function expandChatEmbedRefs(refs: string[]): Promise<string[]> {
  const queue = [...refs];
  const expanded = new Set<string>();
  while (queue.length > 0) {
    const ref = queue.shift();
    if (!ref || expanded.has(ref)) continue;
    expanded.add(ref);
    try {
      const embed = await embedStore.get(ref);
      if (!embed || typeof embed !== 'object') continue;
      const record = embed as Record<string, unknown>;
      const content = typeof record.content === 'string' || (record.content && typeof record.content === 'object')
        ? record.content as string | Record<string, unknown>
        : record;
      const childIds = [...extractEmbedIdsFromContent(content), ...(Array.isArray(record.embed_ids) ? record.embed_ids : [])];
      for (const childId of childIds) {
        if (typeof childId !== 'string') continue;
        const childRef = `embed:${childId.replace(/^embed:/, '')}`;
        if (!expanded.has(childRef)) queue.push(childRef);
      }
    } catch (error) {
      console.warn('[chatSettingsFiles] Failed to inspect embed children:', ref, error);
    }
  }
  return Array.from(expanded);
}

async function loadEmbedFileRows(contentRef: string): Promise<ChatFileRow[]> {
  const embed = await embedStore.get(contentRef);
  if (!embed || typeof embed !== 'object') return [];
  const embedId = contentRef.replace(/^embed:/, '');
  const record = embed as Record<string, unknown>;
  if (typeof record.type === 'string' && normalizeEmbedType(record.type) === 'design-embroidery') {
    const content = typeof record.content === 'string' ? await decodeToonContent(record.content) : record.content;
    if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
    const status = typeof record.status === 'string' ? record.status : undefined;
    const design = readEmbroideryDesign(content as Record<string, unknown>, status);
    if (design.status !== 'finished') return [];
    // Match the filenames offered in the embroidery result.
    const baseName = design.title.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48).replace(/-+$/, '') || 'embroidery-design';
    return EMBROIDERY_FORMATS.flatMap((format): ChatFileRow[] => {
      const file = design.files[format];
      if (!file || !design.aesKey || !hasMediaEncryptionMetadata(file, file.aes_nonce ?? design.aesNonce)) return [];
      const label = format.toUpperCase();
      return [{
        embedId,
        contentRef: `${contentRef}:${format}`,
        title: `${baseName}.${format}`,
        subtitle: label,
        type: 'design-embroidery',
        nodeType: 'design-embroidery',
        iconName: 'embroidery',
        createdAt: Number(record.createdAt) || 0,
        updatedAt: Number(record.updatedAt) || 0,
        metadata: label,
        readBlob: () => readEmbroideryFile(design, format),
      }];
    });
  }
  const rows = getEmbedFileReferences({
    embedId,
    type: typeof record.type === 'string' ? record.type : null,
    content: typeof record.content === 'string' || (record.content && typeof record.content === 'object')
      ? record.content as string | Record<string, unknown>
      : record,
    parent_embed_id: typeof record.parent_embed_id === 'string' ? record.parent_embed_id : null,
    embed_ids: Array.isArray(record.embed_ids) ? record.embed_ids.filter((id): id is string => typeof id === 'string') : null,
    app_id: typeof record.app_id === 'string' ? record.app_id : null,
    skill_id: typeof record.skill_id === 'string' ? record.skill_id : null,
  });
  return rows.map(normalizeStaticRow);
}

export async function loadChatFileRows(messages: Message[]): Promise<ChatFileRow[]> {
  const refs = await expandChatEmbedRefs(extractChatEmbedRefs(messages));
  if (refs.length === 0) return [];
  const files = await embedStore.getUploadedFilesByContentRefs(refs);
  const rows: ChatFileRow[] = files
    .filter(isDownloadable)
    .map((file) => ({ ...file, metadata: buildMetadata(file) }));
  const listedRefs = new Set(rows.map((row) => row.contentRef));
  const listedEmbedIds = new Set(rows.map((row) => row.embedId));
  for (const ref of refs) {
    if (listedRefs.has(ref)) continue;
    const embedId = ref.replace(/^embed:/, '');
    if (listedEmbedIds.has(embedId)) continue;
    const embedRows = await loadEmbedFileRows(ref);
    if (embedRows.some((row) => listedEmbedIds.has(row.embedId))) continue;
    for (const row of embedRows) {
      if (listedRefs.has(row.contentRef)) continue;
      rows.push(row);
      listedRefs.add(row.contentRef);
      listedEmbedIds.add(row.embedId);
    }
  }
  return rows;
}
