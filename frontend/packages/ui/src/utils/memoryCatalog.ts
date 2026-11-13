/**
 * Pure Memory catalog builder for the send path.
 *
 * The catalog is metadata only (id, title, when_to_use, load_mode, source).
 * Out-of-window and mention_only memories never appear in it, so the server
 * never sees them before an explicit mention. Spec: app-memories (draft v4),
 * app-memories.expiry.client-enforced and the load_modes example.
 */
import {
  MAX_RULE_CATALOG_CHARS, MAX_RULE_DOCUMENTS, isMemoryActive, parseRuleDocument,
  type CustomRuleDocument, type MemoryLoadMode,
} from './ruleDocuments';

export interface MemoryCatalogEntry {
  id: string;
  title: string;
  /** Blank means always considered. */
  when_to_use: string;
  load_mode: Exclude<MemoryLoadMode, 'mention_only'>;
  source: 'personal' | 'project';
}

/** Metadata only: memory bodies are never part of a chat request (app-memories.load-modes). */
export interface MemoryCatalogResult {
  catalog: MemoryCatalogEntry[];
}

export function buildMemoryCatalog(
  documents: readonly CustomRuleDocument[], now: Date | number = Date.now(),
): MemoryCatalogResult {
  const catalog: MemoryCatalogEntry[] = [];
  let chars = 0;
  for (const document of documents) {
    if (catalog.length >= MAX_RULE_DOCUMENTS) break;
    const fields = parseRuleDocument(document.document);
    const loadMode = fields.load_mode ?? 'auto_include';
    if (loadMode === 'mention_only' || !isMemoryActive(fields, now)) continue;
    if (chars + document.document.length > MAX_RULE_CATALOG_CHARS) continue;
    chars += document.document.length;
    catalog.push({
      id: document.id, title: fields.title, when_to_use: fields.when_to_use,
      load_mode: loadMode, source: document.source,
    });
  }
  return { catalog };
}
