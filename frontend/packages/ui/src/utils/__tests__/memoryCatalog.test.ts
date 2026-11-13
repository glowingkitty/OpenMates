import { describe, expect, it } from 'vitest';
import { buildMemoryCatalog } from '../memoryCatalog';
import { serializeRuleDocument, type CustomRuleDocument, type RuleDocumentFields } from '../ruleDocuments';

const NOW = Date.parse('2026-06-15T12:00:00Z');
const doc = (id: string, fields: Partial<RuleDocumentFields> = {}, source: 'personal' | 'project' = 'personal'): CustomRuleDocument => ({
  id, source, ...(source === 'project' ? { project_id: 'p1' } : {}),
  document: serializeRuleDocument({ title: `Title ${id}`, when_to_use: '', body: `Body ${id}`, ...fields }),
});

// contract-test: supporting surface=gui.web assertions=app-memories.expiry.client-enforced,app-memories.load-modes
describe('buildMemoryCatalog', () => {
  it('defaults to auto_include and keeps metadata only in the catalog', () => {
    const result = buildMemoryCatalog([doc('a', { when_to_use: 'Writing Python' })], NOW);
    expect(result.catalog).toEqual([{ id: 'a', title: 'Title a', when_to_use: 'Writing Python', load_mode: 'auto_include', source: 'personal' }]);
    expect(JSON.stringify(result.catalog)).not.toContain('Body a');
    expect(Object.keys(result)).toEqual(['catalog']);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('excludes mention_only and out-of-window memories from the catalog', () => {
    const result = buildMemoryCatalog([
      doc('ask', { load_mode: 'ask_first' }),
      doc('mention', { load_mode: 'mention_only' }),
      doc('future', { valid_from: '2026-07-01T00:00:00Z' }),
      doc('expired', { valid_until: '2026-06-01T00:00:00Z' }),
      doc('current', { valid_from: '2026-06-01T00:00:00Z', valid_until: '2026-06-30T00:00:00Z' }, 'project'),
    ], NOW);
    expect(result.catalog.map((entry) => entry.id)).toEqual(['ask', 'current']);
    expect(result.catalog[0].load_mode).toBe('ask_first');
    expect(result.catalog[1].source).toBe('project');
    expect(JSON.stringify(result)).not.toContain('Body ');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('bounds the catalog to 24 documents', () => {
    const docs = Array.from({ length: 30 }, (_, index) => doc(`m${index}`));
    expect(buildMemoryCatalog(docs, NOW).catalog).toHaveLength(24);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('bounds total body characters to 64k', () => {
    const big = (id: string) => doc(id, { body: 'x'.repeat(19_000) });
    const result = buildMemoryCatalog([big('a'), big('b'), big('c'), big('d'), doc('small')], NOW);
    expect(result.catalog.map((entry) => entry.id)).toEqual(['a', 'b', 'c', 'small']);
  });
});
