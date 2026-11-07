/** Shared first-party Rule format; source ownership and access remain caller-owned. */
import { isAlias, parseDocument, stringify, visit } from 'yaml';

export const MAX_RULE_DOCUMENT_CHARS = 24_000;
export const MAX_RULE_DOCUMENTS = 24;
export const MAX_RULE_CATALOG_CHARS = 64_000;

export type MemoryLoadMode = 'auto_include' | 'ask_first' | 'mention_only';
export const MEMORY_LOAD_MODES: readonly MemoryLoadMode[] = ['auto_include', 'ask_first', 'mention_only'];
export const MAX_MEMORY_REFERENCES = 50;

export interface MemoryReference {
  kind: 'embed';
  id: string;
}

export interface RuleDocumentFields {
  title: string;
  /** Legacy summary; absent in the canonical shape. */
  description?: string;
  /** Blank means always considered. */
  when_to_use: string;
  body: string;
  load_mode?: MemoryLoadMode;
  valid_from?: string;
  valid_until?: string;
  references?: MemoryReference[];
}

export interface CustomRuleDocument {
  id: string;
  source: 'personal' | 'project';
  project_id?: string;
  document: string;
  /** Current encrypted Project item receipt; required for automatic context loading. */
  item_revision?: string;
}

export function parseRuleDocument(document: string): RuleDocumentFields {
  if (typeof document !== 'string' || document.length > MAX_RULE_DOCUMENT_CHARS) {
    throw new Error('invalid_rule_document');
  }
  const match = document.replace(/^\uFEFF/, '').match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/);
  if (!match) throw new Error('invalid_rule_document');
  const parsed = parseDocument(match[1], { uniqueKeys: true, schema: 'core' });
  if (parsed.errors.length) throw new Error('invalid_rule_document');
  visit(parsed, (_key, node) => {
    if (isAlias(node)) throw new Error('invalid_rule_document');
  });
  const header: unknown = parsed.toJS({ maxAliasCount: 0 });
  if (!header || typeof header !== 'object' || Array.isArray(header)) throw new Error('invalid_rule_document');
  const record = header as Record<string, unknown>;
  const allowed = ['title', 'description', 'when_to_use', 'load_mode', 'valid_from', 'valid_until', 'references'];
  if (Object.keys(record).some((key) => !allowed.includes(key)) || !('title' in record)) throw new Error('invalid_rule_document');
  const text = (field: string, max: number): string | undefined => {
    if (!(field in record)) return undefined;
    const value = record[field];
    if (typeof value !== 'string' || !value.trim() || value.trim().length > max) throw new Error('invalid_rule_document');
    return value.trim();
  };
  const body = match[2].trim();
  if (!body || body.length > 20_000) throw new Error('invalid_rule_document');
  const fields: RuleDocumentFields = { title: text('title', 180) as string, when_to_use: text('when_to_use', 1200) ?? '', body };
  const description = text('description', 1200);
  if (description !== undefined) fields.description = description;
  if ('load_mode' in record) {
    if (!MEMORY_LOAD_MODES.includes(record.load_mode as MemoryLoadMode)) throw new Error('invalid_rule_document');
    fields.load_mode = record.load_mode as MemoryLoadMode;
  }
  for (const field of ['valid_from', 'valid_until'] as const) {
    if (!(field in record)) continue;
    const value = record[field];
    const iso = value instanceof Date ? value.toISOString() : value;
    if (typeof iso !== 'string' || !Number.isFinite(Date.parse(iso))) throw new Error('invalid_rule_document');
    fields[field] = iso;
  }
  if (fields.valid_from && fields.valid_until && Date.parse(fields.valid_from) > Date.parse(fields.valid_until)) {
    throw new Error('invalid_rule_document');
  }
  if ('references' in record) {
    const refs = record.references;
    if (!Array.isArray(refs) || refs.length > MAX_MEMORY_REFERENCES) throw new Error('invalid_rule_document');
    const seen = new Set<string>();
    // Legacy stored chat references are dropped on read; only embed references remain supported.
    const embedRefs = refs.filter((ref) => !(ref && typeof ref === 'object' && !Array.isArray(ref)
      && (ref as Record<string, unknown>).kind === 'chat'));
    fields.references = embedRefs.map((ref) => {
      if (!ref || typeof ref !== 'object' || Array.isArray(ref)) throw new Error('invalid_rule_document');
      const entry = ref as Record<string, unknown>;
      if (Object.keys(entry).length !== 2 || entry.kind !== 'embed'
        || typeof entry.id !== 'string' || !entry.id.trim() || entry.id.length > 240) throw new Error('invalid_rule_document');
      const key = `${entry.kind}:${entry.id}`;
      if (seen.has(key)) throw new Error('invalid_rule_document');
      seen.add(key);
      return { kind: 'embed' as const, id: entry.id };
    });
  }
  return fields;
}

export function serializeRuleDocument(fields: RuleDocumentFields): string {
  const header: Record<string, unknown> = { title: fields.title.trim() };
  if (fields.description?.trim()) header.description = fields.description.trim();
  if (fields.when_to_use.trim()) header.when_to_use = fields.when_to_use.trim();
  if (fields.load_mode) header.load_mode = fields.load_mode;
  if (fields.valid_from) header.valid_from = fields.valid_from;
  if (fields.valid_until) header.valid_until = fields.valid_until;
  if (fields.references?.length) header.references = fields.references.map(({ kind, id }) => ({ kind, id }));
  const document = `---\n${stringify(header)}---\n${fields.body.trim()}\n`;
  parseRuleDocument(document);
  return document;
}

type MemoryWindow = Pick<RuleDocumentFields, 'valid_from' | 'valid_until'>;

/** True when `now` is inside the optional start/expiry window (both bounds inclusive). */
export function isMemoryActive(fields: MemoryWindow, now: Date | number = Date.now()): boolean {
  const time = typeof now === 'number' ? now : now.getTime();
  if (fields.valid_from && time < Date.parse(fields.valid_from)) return false;
  if (fields.valid_until && time > Date.parse(fields.valid_until)) return false;
  return true;
}

/** True as soon as the expiry is in the past (no grace window); clients then delete the memory. */
export function isMemoryExpired(fields: MemoryWindow, now: Date | number = Date.now()): boolean {
  if (!fields.valid_until) return false;
  const time = typeof now === 'number' ? now : now.getTime();
  return time > Date.parse(fields.valid_until);
}

export function validateRuleCatalog(documents: CustomRuleDocument[]): CustomRuleDocument[] {
  if (documents.length > MAX_RULE_DOCUMENTS) throw new Error('rule_catalog_limit');
  let size = 0;
  const identities = new Set<string>();
  for (const rule of documents) {
    if (!rule.id || rule.id.length > 240 || identities.has(rule.id) || rule.id.startsWith('app:')
      || !['personal', 'project'].includes(rule.source)
      || rule.source === 'project' && !rule.project_id
      || rule.source === 'personal' && rule.project_id !== undefined) throw new Error('invalid_rule_document');
    parseRuleDocument(rule.document);
    identities.add(rule.id);
    size += rule.document.length;
  }
  if (size > MAX_RULE_CATALOG_CHARS) throw new Error('rule_catalog_limit');
  return documents;
}

export function buildWholeDocumentPatch(original: string, updated: string, path: string): string {
  if (original.includes('\r') || updated.includes('\r')) throw new Error('project_document_line_endings');
  const lines = (value: string) => {
    if (!value) return [];
    const entries = value.split('\n');
    if (value.endsWith('\n')) entries.pop();
    return entries.map((text, index) => ({ text, hasNewline: index < entries.length - 1 || value.endsWith('\n') }));
  };
  const before = lines(original);
  const after = lines(updated);
  const encode = (entries: ReturnType<typeof lines>, prefix: string) => entries.flatMap((line) => [
    `${prefix}${line.text}`, ...(!line.hasNewline ? ['\\ No newline at end of file'] : []),
  ]);
  return [`--- a/${path}`, `+++ b/${path}`, `@@ -${before.length ? 1 : 0},${before.length} +${after.length ? 1 : 0},${after.length} @@`,
    ...encode(before, '-'), ...encode(after, '+')].join('\n') + '\n';
}
