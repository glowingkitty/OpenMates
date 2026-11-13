/**
 * Rows of Settings > Memories: parsed fields, expired state, sort orders and the
 * modified date shown on the second line. Pure; the list component renders the result.
 * Spec: app-memories (Settings > Memories list).
 */
import type { EditableRuleDocument } from '../services/ruleDocumentService';
import { isMemoryExpired, parseRuleDocument, type RuleDocumentFields } from './ruleDocuments';

export type MemorySort = 'modified' | 'added' | 'title';
export const MEMORY_SORTS: readonly MemorySort[] = ['modified', 'added', 'title'];
export const DEFAULT_MEMORY_SORT: MemorySort = 'modified';

export interface MemoryListEntry {
  document: EditableRuleDocument;
  fields: RuleDocumentFields;
  expired: boolean;
  /** Position in storage; later entries were stored more recently. */
  index: number;
}

export function memoryListEntries(documents: readonly EditableRuleDocument[], now: number = Date.now()): MemoryListEntry[] {
  return documents.map((document, index) => {
    const fields = parseRuleDocument(document.document);
    return { document, fields, expired: isMemoryExpired(fields, now), index };
  });
}

/** Last change in unix seconds; a memory saved once has only created_at. */
export function memoryModifiedAt(fields: Pick<RuleDocumentFields, 'created_at' | 'updated_at'>): number | undefined {
  return fields.updated_at ?? fields.created_at;
}

function byTimestamp(pick: (entry: MemoryListEntry) => number | undefined) {
  return (a: MemoryListEntry, b: MemoryListEntry): number => {
    const left = pick(a), right = pick(b);
    if (left !== undefined && right !== undefined && left !== right) return right - left;
    // Entries without a timestamp follow the ones that have one.
    if (left === undefined && right !== undefined) return 1;
    if (right === undefined && left !== undefined) return -1;
    return b.index - a.index;
  };
}

/** Newest first by the chosen time; untimed memories last, newest stored first. Title sort is A–Z. */
export function sortMemoryEntries(entries: readonly MemoryListEntry[], sort: MemorySort, locale = 'en'): MemoryListEntry[] {
  const sorted = [...entries];
  if (sort === 'title') {
    const collator = new Intl.Collator(locale, { sensitivity: 'base', numeric: true });
    return sorted.sort((a, b) => collator.compare(a.fields.title, b.fields.title) || b.index - a.index);
  }
  return sorted.sort(byTimestamp((entry) => sort === 'added' ? entry.fields.created_at : memoryModifiedAt(entry.fields)));
}

/** Case-insensitive title/when-to-use match; an empty query keeps every entry. */
export function filterMemoryEntries(entries: readonly MemoryListEntry[], query: string): MemoryListEntry[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [...entries];
  return entries.filter((entry) => `${entry.fields.title}\n${entry.fields.when_to_use}`.toLocaleLowerCase().includes(needle));
}

/** Medium date in the UI locale; '' when the memory has no stored time. */
export function formatMemoryDate(seconds: number | undefined, locale = 'en'): string {
  if (seconds === undefined || !Number.isFinite(seconds)) return '';
  const date = new Date(seconds * 1000);
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
}
