/**
 * Client-side responder for server Memory requests (`memory:<id>` keys).
 *
 * Memory bodies are never sent with a chat request. When the server selects
 * catalogued memories it asks for them by id; the client decides from its OWN
 * stored load_mode and validity window (never a server-claimed mode):
 * auto_include answers silently, ask_first needs the consent dialog,
 * mention_only / out-of-window / unknown ids are never answered with content.
 * Spec: app-memories.load-modes. This module is the single adapter for the
 * wire names; bodies must never be logged.
 */
import { isMemoryActive, parseRuleDocument, type CustomRuleDocument } from '../utils/ruleDocuments';

/** Requested keys are `memory-<id>`; ids may contain hyphens, so only the leading prefix is stripped. */
export const MEMORY_REQUEST_KEY_PREFIX = 'memory-';
/** Wire app_id of memory documents in confirmed entries and dialog categories (item_key = memory id). */
export const MEMORY_RESPONSE_APP_ID = 'memory';

export interface ResolvedMemory {
  id: string;
  title: string;
  /** Canonical Markdown document. Never log. */
  document: string;
  source: CustomRuleDocument['source'];
}

export interface MemoryRequestDecision {
  auto: ResolvedMemory[];
  ask: ResolvedMemory[];
  /** Requested ids that must never receive content (mention_only, expired, unknown). */
  withheld: string[];
}

export function isMemoryRequestKey(key: string): boolean {
  return key.startsWith(MEMORY_REQUEST_KEY_PREFIX) && key.length > MEMORY_REQUEST_KEY_PREFIX.length;
}

export function memoryIdsFromRequestedKeys(keys: readonly string[]): string[] {
  return Array.from(new Set(keys.filter(isMemoryRequestKey).map((key) => key.slice(MEMORY_REQUEST_KEY_PREFIX.length))));
}

/** Dialog category key (`app_id-item_type` format) for a memory id. */
export function memoryDialogKey(id: string): string { return `${MEMORY_REQUEST_KEY_PREFIX}${id}`; }

/** The stored canonical document is sent unchanged so title/when_to_use match the catalog. */
export function memoryResponseEntry(memory: ResolvedMemory): { app_id: string; item_key: string; content: string } {
  return { app_id: MEMORY_RESPONSE_APP_ID, item_key: memory.id, content: memory.document };
}

/** Pure decision from local documents only; the server's claimed mode is not an input. */
export function decideMemoryRequest(
  requestedIds: readonly string[], documents: readonly CustomRuleDocument[], now: Date | number = Date.now(),
  serverTitles: Readonly<Record<string, string>> = {},
): MemoryRequestDecision {
  const byId = new Map(documents.map((document) => [document.id, document]));
  const decision: MemoryRequestDecision = { auto: [], ask: [], withheld: [] };
  for (const id of new Set(requestedIds)) {
    const document = byId.get(id);
    if (!document) { decision.withheld.push(id); continue; }
    const fields = parseRuleDocument(document.document);
    if (!isMemoryActive(fields, now)) { decision.withheld.push(id); continue; }
    const resolved: ResolvedMemory = { id, title: fields.title || serverTitles[id] || id, document: document.document, source: document.source };
    const mode = fields.load_mode ?? 'auto_include';
    if (mode === 'auto_include') decision.auto.push(resolved);
    else if (mode === 'ask_first') decision.ask.push(resolved);
    else decision.withheld.push(id);
  }
  return decision;
}

/**
 * Memory documents stored locally: personal ones plus, when the chat has an active Project
 * focus, that Project's Memories. A failure to read Project documents withholds only those ids.
 */
export async function loadLocalMemoryDocuments(chatId?: string): Promise<CustomRuleDocument[]> {
  const { listPersonalRuleDocuments, listProjectRuleDocuments } = await import('./ruleDocumentService');
  const personal = await listPersonalRuleDocuments();
  if (!chatId) return personal;
  try {
    const { getActiveProjectFocus } = await import('./projectService');
    const focus = await getActiveProjectFocus(chatId);
    if (!focus) return personal;
    const project = await listProjectRuleDocuments({ chatId, projectId: focus.project_id });
    return [...personal, ...project.filter((document) => document.id)];
  } catch (error) {
    console.warn('[memoryDocumentRequest] Project Memories unavailable; withholding them', error);
    return personal;
  }
}
