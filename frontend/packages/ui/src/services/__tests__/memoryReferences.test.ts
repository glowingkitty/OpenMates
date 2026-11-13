import { describe, expect, it, vi } from 'vitest';
import {
  REFERENCE_TRUNCATED_MARKER, REFERENCE_UNAVAILABLE_MARKER, lookupReferenceLabels, memoryEntryWithReferences,
  resolveMemoryReferences, type ReferenceReaders,
} from '../memoryReferences';
import { serializeRuleDocument } from '../../utils/ruleDocuments';

const readers = (over: Partial<ReferenceReaders> = {}): ReferenceReaders => ({
  readEmbed: async (id) => (id === 'e1' ? { title: 'Spec sheet', content: 'EMBED BODY' } : null),
  ...over,
});

describe('resolveMemoryReferences', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('appends embed content', async () => {
    const result = await resolveMemoryReferences([{ kind: 'embed', id: 'e1' }], readers(), 10_000);
    expect(result.section).toContain('EMBED BODY');
    expect(result.referencesUnavailable).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('never follows references inside referenced items (depth 1)', async () => {
    const nested = serializeRuleDocument({ title: 'Nested', when_to_use: '', body: 'x', references: [{ kind: 'embed', id: 'e1' }] });
    const readEmbed = vi.fn(async () => ({ title: 'Doc', content: nested }));
    await resolveMemoryReferences([{ kind: 'embed', id: 'e9' }], { readEmbed }, 20_000);
    expect(readEmbed).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('marks unavailable, undecryptable or throwing references without failing', async () => {
    const result = await resolveMemoryReferences(
      [{ kind: 'embed', id: 'gone' }, { kind: 'embed', id: 'boom' }],
      readers({ readEmbed: async (id) => { if (id === 'boom') throw new Error('decrypt'); return null; } }), 10_000);
    expect(result.section.split(REFERENCE_UNAVAILABLE_MARKER)).toHaveLength(3);
    expect(result.referencesUnavailable).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('marks embed truncation inside the budget', async () => {
    const big = await resolveMemoryReferences([{ kind: 'embed', id: 'e1' }],
      readers({ readEmbed: async () => ({ title: 'Big', content: 'x'.repeat(5_000) }) }), 1_000);
    expect(big.section).toContain(REFERENCE_TRUNCATED_MARKER);
    expect(big.section.length).toBeLessThanOrEqual(1_000);
    expect(big.referencesUnavailable).toBe(true);
  });
});

describe('memoryEntryWithReferences', () => {
  const document = serializeRuleDocument({
    title: 'Trip', when_to_use: '', body: 'Body', references: [{ kind: 'embed', id: 'e1' }],
  });
  const base = { app_id: 'memory', item_key: 'm1', content: document };

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('keeps the canonical document first and flags unavailable references', async () => {
    const entry = await memoryEntryWithReferences(base, readers());
    expect(entry.content.startsWith(document)).toBe(true);
    expect(entry.references_unavailable).toBeUndefined();
    const missing = await memoryEntryWithReferences(base, readers({ readEmbed: async () => null }));
    expect(missing.references_unavailable).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('skips references the user deselected in the approval dialog', async () => {
    const entry = await memoryEntryWithReferences(base, readers(), () => false);
    expect(entry).toBe(base);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('returns memories without references unchanged', async () => {
    const plain = { ...base, content: serializeRuleDocument({ title: 'P', when_to_use: '', body: 'b' }) };
    expect(await memoryEntryWithReferences(plain, readers())).toBe(plain);
  });
});

describe('lookupReferenceLabels', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('lists titles for the approval dialog and labels unavailable items', async () => {
    const labels = await lookupReferenceLabels([{ kind: 'embed', id: 'e1' }, { kind: 'embed', id: 'nope' }], readers());
    expect(labels.map((l) => [l.title, l.available])).toEqual([['Spec sheet', true], [REFERENCE_UNAVAILABLE_MARKER, false]]);
  });
});
