/** Shared first-party Rule format; source ownership and access remain caller-owned. */
import { isAlias, parseDocument, stringify, visit } from 'yaml';

export const MAX_RULE_DOCUMENT_CHARS = 24_000;
export const MAX_RULE_DOCUMENTS = 24;
export const MAX_RULE_CATALOG_CHARS = 64_000;

export interface RuleDocumentFields {
  title: string;
  description: string;
  when_to_use: string;
  body: string;
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
  const fields = ['title', 'description', 'when_to_use'] as const;
  if (Object.keys(record).length !== fields.length) throw new Error('invalid_rule_document');
  for (const field of fields) {
    if (typeof record[field] !== 'string' || !record[field].trim()
      || record[field].trim().length > (field === 'title' ? 180 : 1200)) {
      throw new Error('invalid_rule_document');
    }
  }
  const body = match[2].trim();
  if (!body || body.length > 20_000) throw new Error('invalid_rule_document');
  return {
    title: (record.title as string).trim(), description: (record.description as string).trim(),
    when_to_use: (record.when_to_use as string).trim(), body,
  };
}

export function serializeRuleDocument(fields: RuleDocumentFields): string {
  const document = `---\n${stringify({
    title: fields.title.trim(), description: fields.description.trim(), when_to_use: fields.when_to_use.trim(),
  })}---\n${fields.body.trim()}\n`;
  parseRuleDocument(document);
  return document;
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
