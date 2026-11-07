import { describe, expect, it, vi } from 'vitest';
import {
  REFERENCE_TRUNCATED_MARKER, REFERENCE_UNAVAILABLE_MARKER, lookupReferenceLabels, memoryEntryWithReferences,
  resolveMemoryReferences, type ReferenceReaders,
} from '../memoryReferences';
import { serializeRuleDocument } from '../../utils/ruleDocuments';

const readers = (over: Partial<ReferenceReaders> = {}): ReferenceReaders => ({
  readEmbed: async (id) => (id === 'e1' ? { title: 'Spec sheet', content: 'EMBED BODY' } : null),
  readChat: async (id) => (id === 'c1' ? { title: 'Trip plan', summary: 'Plans for Lisbon', lastUpdated: 1_700_000_000 } : null),
  ...over,
});

// contract-test: direct surface=gui.web assertions=app-memories.references.embeds-and-chats
describe('resolveMemoryReferences', () => {
  it('appends embed content and only chat metadata, and approves exactly the referenced chats', async () => {
    const readChat = vi.fn(readers().readChat);
    const result = await resolveMemoryReferences(
      [{ kind: 'embed', id: 'e1' }, { kind: 'chat', id: 'c1' }], readers({ readChat }), 10_000);
    expect(result.section).toContain('EMBED BODY');
    expect(result.section).toContain('Trip plan');
    expect(result.section).toContain('chat id: c1');
    expect(result.section).toContain('Plans for Lisbon');
    expect(result.section).toContain('last updated');
    expect(result.approvedSearchChatIds).toEqual(['c1']);
    expect(result.referencesUnavailable).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.references.embeds-and-chats
  it('never follows references inside referenced items (depth 1)', async () => {
    const nested = serializeRuleDocument({ title: 'Nested', when_to_use: '', body: 'x', references: [{ kind: 'chat', id: 'c1' }] });
    const readEmbed = vi.fn(async () => ({ title: 'Doc', content: nested }));
    const readChat = vi.fn(readers().readChat);
    const result = await resolveMemoryReferences([{ kind: 'embed', id: 'e9' }], { readEmbed, readChat }, 20_000);
    expect(readEmbed).toHaveBeenCalledTimes(1);
    expect(readChat).not.toHaveBeenCalled();
    expect(result.approvedSearchChatIds).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.references.embeds-and-chats
  it('marks unavailable, undecryptable or throwing references without failing and without approving them', async () => {
    const result = await resolveMemoryReferences(
      [{ kind: 'embed', id: 'gone' }, { kind: 'chat', id: 'gone' }, { kind: 'embed', id: 'boom' }],
      readers({ readEmbed: async (id) => { if (id === 'boom') throw new Error('decrypt'); return null; } }), 10_000);
    expect(result.section.split(REFERENCE_UNAVAILABLE_MARKER)).toHaveLength(4);
    expect(result.referencesUnavailable).toBe(true);
    expect(result.approvedSearchChatIds).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.references.embeds-and-chats
  it('caps approved chats at 10 and marks embed truncation inside the budget', async () => {
    const many = Array.from({ length: 14 }, (_, i) => ({ kind: 'chat' as const, id: `c${i}` }));
    const chats = await resolveMemoryReferences(many, readers({ readChat: async (id) => ({ title: id, summary: '', lastUpdated: null }) }), 50_000);
    expect(chats.approvedSearchChatIds).toHaveLength(10);
    const big = await resolveMemoryReferences([{ kind: 'embed', id: 'e1' }],
      readers({ readEmbed: async () => ({ title: 'Big', content: 'x'.repeat(5_000) }) }), 1_000);
    expect(big.section).toContain(REFERENCE_TRUNCATED_MARKER);
    expect(big.section.length).toBeLessThanOrEqual(1_000);
    expect(big.referencesUnavailable).toBe(true);
  });
});

// contract-test: direct surface=gui.web assertions=app-memories.references.embeds-and-chats
describe('memoryEntryWithReferences', () => {
  const document = serializeRuleDocument({
    title: 'Trip', when_to_use: '', body: 'Body', references: [{ kind: 'chat', id: 'c1' }, { kind: 'embed', id: 'e1' }],
  });
  const base = { app_id: 'memory', item_key: 'm1', content: document };

  it('keeps the canonical document first and adds the approved chat ids and unavailable flag', async () => {
    const entry = await memoryEntryWithReferences(base, readers());
    expect(entry.content.startsWith(document)).toBe(true);
    expect(entry.approved_search_chat_ids).toEqual(['c1']);
    expect(entry.references_unavailable).toBeUndefined();
    const missing = await memoryEntryWithReferences(base, readers({ readChat: async () => null }));
    expect(missing.references_unavailable).toBe(true);
    expect(missing.approved_search_chat_ids).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.references.embeds-and-chats
  it('skips references the user deselected in the approval dialog', async () => {
    const entry = await memoryEntryWithReferences(base, readers(), (ref) => ref.kind !== 'chat');
    expect(entry.approved_search_chat_ids).toBeUndefined();
    expect(entry.content).toContain('EMBED BODY');
    expect(entry.content).not.toContain('Trip plan');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.references.embeds-and-chats
  it('returns memories without references unchanged', async () => {
    const plain = { ...base, content: serializeRuleDocument({ title: 'P', when_to_use: '', body: 'b' }) };
    expect(await memoryEntryWithReferences(plain, readers())).toBe(plain);
  });
});

// contract-test: direct surface=gui.web assertions=app-memories.references.embeds-and-chats
describe('lookupReferenceLabels', () => {
  it('lists titles for the approval dialog and labels unavailable items', async () => {
    const labels = await lookupReferenceLabels([{ kind: 'chat', id: 'c1' }, { kind: 'embed', id: 'nope' }], readers());
    expect(labels.map((l) => [l.title, l.available])).toEqual([['Trip plan', true], [REFERENCE_UNAVAILABLE_MARKER, false]]);
  });
});
