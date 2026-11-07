/**
 * Client-side resolution of Memory references (embeds and chats).
 * Spec: app-memories.references.embeds-and-chats.
 *
 * Runs only on a client holding the reader's keys, when the client answers a
 * server Memory request. Depth is exactly 1: references inside a referenced
 * item are never followed. Embeds contribute their decrypted content within a
 * character budget (overflow is marked, never silent); chats contribute ONLY
 * title, id, summary and last-updated time, never messages. An unavailable,
 * undecryptable or deleted item yields a marker line and an unavailable flag,
 * never an error. Referenced chat ids are returned as `approved_search_chat_ids`
 * (the user's consent for the main processor to search exactly those chats).
 * Bodies and summaries must never be logged.
 */
import { MAX_RULE_DOCUMENT_CHARS, parseRuleDocument, type MemoryReference } from '../utils/ruleDocuments';

/** Wire name of the approved chat id list on a Memory response entry and on the confirmation payload. */
export const APPROVED_SEARCH_CHAT_IDS_FIELD = 'approved_search_chat_ids';
export const MAX_APPROVED_SEARCH_CHATS = 10;
export const REFERENCE_UNAVAILABLE_MARKER = 'Reference unavailable';
export const REFERENCE_TRUNCATED_MARKER = '[Referenced content truncated: budget reached]';
const MAX_CHAT_SUMMARY_CHARS = 600;
const MIN_EMBED_SLICE_CHARS = 200;

export interface EmbedReferenceData { title: string; content: string }
export interface ChatReferenceMetadata { title: string; summary: string; lastUpdated: number | null }
export interface ReferenceReaders {
  /** Decrypted embed with the reader's keys, or null when missing/undecryptable/deleted. */
  readEmbed(id: string): Promise<EmbedReferenceData | null>;
  /** Chat metadata only. Implementations must never return message content. */
  readChat(id: string): Promise<ChatReferenceMetadata | null>;
}

export interface ReferenceLabel { reference: MemoryReference; title: string; available: boolean }
export interface ResolvedReferences {
  /** Markdown section to append to the Memory document ('' when no references). */
  section: string;
  /** True when at least one reference was unavailable or truncated. */
  referencesUnavailable: boolean;
  approvedSearchChatIds: string[];
}

/** Stable id for a reference row in the approval dialog and editor. */
export function referenceEntryId(reference: MemoryReference): string { return `ref:${reference.kind}:${reference.id}`; }

export function memoryReferencesOf(document: string): MemoryReference[] {
  try { return parseRuleDocument(document).references ?? []; } catch { return []; }
}

export async function defaultReferenceReaders(): Promise<ReferenceReaders> {
  const [{ resolveEmbed }, { chatDB }] = await Promise.all([import('./embedResolver'), import('./db')]);
  return {
    async readEmbed(id) {
      const embed = await resolveEmbed(id);
      if (!embed || embed.status !== 'finished' || typeof embed.content !== 'string' || !embed.content) return null;
      const named = [embed.title, embed.file_path, embed.text_preview].find((v) => typeof v === 'string' && v.trim());
      return { title: String(named ?? embed.type).trim().slice(0, 120), content: embed.content };
    },
    async readChat(id) {
      const chat = await chatDB.getChat(id);
      if (!chat) return null;
      const title = (chat.title ?? '').trim();
      if (!title) return null; // undecryptable metadata counts as unavailable
      const summary = (chat as { chat_summary?: string | null }).chat_summary ?? '';
      return { title, summary: summary.slice(0, MAX_CHAT_SUMMARY_CHARS), lastUpdated: chat.last_edited_overall_timestamp ?? null };
    },
  };
}

async function safely<T>(read: () => Promise<T | null>): Promise<T | null> {
  try { return await read(); } catch { return null; }
}

/** Titles for chips and the ask-first dialog; unavailable items are labelled, never thrown. */
export async function lookupReferenceLabels(references: readonly MemoryReference[], readers: ReferenceReaders): Promise<ReferenceLabel[]> {
  return Promise.all(references.map(async (reference) => {
    const found = reference.kind === 'embed'
      ? await safely(() => readers.readEmbed(reference.id))
      : await safely(() => readers.readChat(reference.id));
    return { reference, title: found?.title ?? REFERENCE_UNAVAILABLE_MARKER, available: found !== null };
  }));
}

/**
 * Resolve references at depth 1 into a section that fits `budgetChars`.
 * `references` should already be filtered by the user's approval selection.
 */
export async function resolveMemoryReferences(
  references: readonly MemoryReference[], readers: ReferenceReaders, budgetChars: number,
): Promise<ResolvedReferences> {
  if (references.length === 0) return { section: '', referencesUnavailable: false, approvedSearchChatIds: [] };
  const lines: string[] = ['', '## Referenced items (data from the reader\'s own embeds and chats)', ''];
  const approved: string[] = [];
  let unavailable = false;
  let remaining = Math.max(0, budgetChars - lines.join('\n').length);
  const mark = (text: string) => { lines.push(text, ''); remaining -= text.length + 2; };
  for (const reference of references) {
    if (reference.kind === 'chat') {
      const chat = await safely(() => readers.readChat(reference.id));
      if (!chat) { unavailable = true; mark(`- ${REFERENCE_UNAVAILABLE_MARKER}: chat ${reference.id}`); continue; }
      const updated = chat.lastUpdated ? new Date(chat.lastUpdated * (chat.lastUpdated < 1e12 ? 1000 : 1)).toISOString() : 'unknown';
      const block = `### Chat: ${chat.title}\n- chat id: ${reference.id}\n- summary: ${chat.summary || 'none'}\n- last updated: ${updated}`;
      mark(block);
      if (approved.length < MAX_APPROVED_SEARCH_CHATS && !approved.includes(reference.id)) approved.push(reference.id);
      continue;
    }
    const embed = await safely(() => readers.readEmbed(reference.id));
    if (!embed) { unavailable = true; mark(`- ${REFERENCE_UNAVAILABLE_MARKER}: embed ${reference.id}`); continue; }
    const header = `### Embed: ${embed.title} (${reference.id})\n`;
    const room = remaining - header.length - REFERENCE_TRUNCATED_MARKER.length - 3; // slice + '\n' + marker, plus the 2 joiner chars each block adds
    if (room < MIN_EMBED_SLICE_CHARS && embed.content.length > Math.max(room, 0)) {
      unavailable = true;
      mark(`${header}${REFERENCE_TRUNCATED_MARKER}`);
    } else if (embed.content.length > room) {
      unavailable = true;
      mark(`${header}${embed.content.slice(0, room)}\n${REFERENCE_TRUNCATED_MARKER}`);
    } else {
      mark(`${header}${embed.content}`);
    }
  }
  return { section: lines.join('\n').trimEnd() + '\n', referencesUnavailable: unavailable, approvedSearchChatIds: approved };
}

export interface MemoryResponseEntryWithReferences {
  app_id: string; item_key: string; content: string;
  references_unavailable?: boolean;
  approved_search_chat_ids?: string[];
}

/** Append the resolved section to the canonical document within the 24k document ceiling. */
export async function memoryEntryWithReferences(
  base: { app_id: string; item_key: string; content: string }, readers: ReferenceReaders,
  isSelected: (reference: MemoryReference) => boolean = () => true,
): Promise<MemoryResponseEntryWithReferences> {
  const references = memoryReferencesOf(base.content).filter(isSelected);
  if (references.length === 0) return base;
  const resolved = await resolveMemoryReferences(references, readers, MAX_RULE_DOCUMENT_CHARS - base.content.length);
  return {
    ...base, content: base.content + resolved.section,
    ...(resolved.referencesUnavailable ? { references_unavailable: true } : {}),
    ...(resolved.approvedSearchChatIds.length ? { [APPROVED_SEARCH_CHAT_IDS_FIELD]: resolved.approvedSearchChatIds } : {}),
  };
}
