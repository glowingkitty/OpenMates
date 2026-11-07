import { describe, expect, it } from 'vitest';
import {
  decideMemoryRequest, memoryDialogKey, memoryIdsFromRequestedKeys, memoryResponseEntry,
} from '../memoryDocumentRequest';
import { serializeRuleDocument, type CustomRuleDocument, type RuleDocumentFields } from '../../utils/ruleDocuments';

const NOW = Date.parse('2026-06-15T12:00:00Z');
const doc = (id: string, fields: Partial<RuleDocumentFields> = {}): CustomRuleDocument => ({
  id, source: 'personal', document: serializeRuleDocument({ title: `Title ${id}`, when_to_use: '', body: `Body ${id}`, ...fields }),
});

// contract-test: supporting surface=gui.web assertions=app-memories.load-modes
describe('decideMemoryRequest', () => {
  it('auto_include answers without a dialog, ask_first requires consent', () => {
    const result = decideMemoryRequest(['a', 'b'], [doc('a', { load_mode: 'auto_include' }), doc('b', { load_mode: 'ask_first' })], NOW);
    expect(result.auto.map((m) => m.id)).toEqual(['a']);
    expect(result.ask.map((m) => m.id)).toEqual(['b']);
    expect(result.withheld).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('treats a missing load_mode as auto_include', () => {
    expect(decideMemoryRequest(['a'], [doc('a')], NOW).auto).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('never answers mention_only memories', () => {
    const result = decideMemoryRequest(['m'], [doc('m', { load_mode: 'mention_only' })], NOW);
    expect(result).toEqual({ auto: [], ask: [], withheld: ['m'] });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('never answers out-of-window memories', () => {
    const result = decideMemoryRequest(['old', 'future'], [
      doc('old', { valid_until: '2026-06-01T00:00:00Z' }), doc('future', { valid_from: '2026-07-01T00:00:00Z' }),
    ], NOW);
    expect(result.auto).toEqual([]);
    expect(result.withheld).toEqual(['old', 'future']);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('never answers unknown ids and ignores unrequested documents', () => {
    const result = decideMemoryRequest(['ghost'], [doc('a')], NOW);
    expect(result).toEqual({ auto: [], ask: [], withheld: ['ghost'] });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('deduplicates repeated ids', () => {
    expect(decideMemoryRequest(['a', 'a'], [doc('a')], NOW).auto).toHaveLength(1);
  });
});

// contract-test: supporting surface=gui.web assertions=app-memories.load-modes
describe('memory request wire adapter', () => {
  it('strips only the leading memory- prefix (ids may contain hyphens) and answers under app_id memory', () => {
    expect(memoryIdsFromRequestedKeys(['memory-personal:a-b-c', 'code-preferred_technologies', 'memory-personal:a-b-c', 'memory-']))
      .toEqual(['personal:a-b-c']);
    const [memory] = decideMemoryRequest(['p1'], [doc('p1')], NOW).auto;
    expect(memoryResponseEntry(memory)).toEqual({ app_id: 'memory', item_key: 'p1', content: memory.document });
    expect(memoryDialogKey('p1')).toBe('memory-p1');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.load-modes
  it('prefers the local title over server memory_titles', () => {
    const [memory] = decideMemoryRequest(['p1'], [doc('p1')], NOW, { p1: 'Server title' }).auto;
    expect(memory.title).toBe('Title p1');
  });
});
