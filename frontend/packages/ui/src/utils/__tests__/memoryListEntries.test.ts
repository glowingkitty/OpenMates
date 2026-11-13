import { describe, expect, it } from 'vitest';
import { serializeRuleDocument, type RuleDocumentFields } from '../ruleDocuments';
import { filterMemoryEntries, formatMemoryDate, memoryListEntries, sortMemoryEntries } from '../memoryListEntries';

function doc(id: string, title: string, extra: Partial<RuleDocumentFields> = {}) {
  return { id, source: 'personal' as const, document: serializeRuleDocument({ title, when_to_use: '', body: `${title} body`, ...extra }) };
}

const documents = [
  doc('personal:old-untimed', 'Bravo'),
  doc('personal:added-early', 'Charlie', { created_at: 100, updated_at: 900 }),
  doc('personal:added-late', 'alpha', { created_at: 500 }),
  doc('personal:new-untimed', 'Delta', { valid_until: '2020-01-01T00:00:00.000Z' }),
];
const ids = (sorted: ReturnType<typeof memoryListEntries>) => sorted.map((entry) => entry.document.id);

describe('Settings > Memories list order', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
  it('sorts by last modification by default, untimed memories last and newest stored first', () => {
    expect(ids(sortMemoryEntries(memoryListEntries(documents), 'modified')))
      .toEqual(['personal:added-early', 'personal:added-late', 'personal:new-untimed', 'personal:old-untimed']);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
  it('sorts by creation time and by title A–Z', () => {
    expect(ids(sortMemoryEntries(memoryListEntries(documents), 'added')))
      .toEqual(['personal:added-late', 'personal:added-early', 'personal:new-untimed', 'personal:old-untimed']);
    expect(sortMemoryEntries(memoryListEntries(documents), 'title').map((entry) => entry.fields.title))
      .toEqual(['alpha', 'Bravo', 'Charlie', 'Delta']);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape,app-memories.expiry.client-enforced
  it('marks expired memories and filters by title', () => {
    const entries = memoryListEntries(documents, Date.parse('2026-06-01T00:00:00Z'));
    expect(entries.filter((entry) => entry.expired).map((entry) => entry.document.id)).toEqual(['personal:new-untimed']);
    expect(ids(filterMemoryEntries(entries, 'CHAR'))).toEqual(['personal:added-early']);
    expect(filterMemoryEntries(entries, '  ')).toHaveLength(4);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
  it('formats a stored time and omits an unknown one', () => {
    expect(formatMemoryDate(1_700_000_000, 'en')).toMatch(/2023/);
    expect(formatMemoryDate(undefined)).toBe('');
  });
});
