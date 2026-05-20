import { describe, expect, it } from 'vitest';
import { dedupeShareChatEmbeds, deriveParentByChildEmbeds, normalizeEmbedIds } from './shareChatEmbedUtils';

describe('normalizeEmbedIds', () => {
  it('normalizes array and pipe-delimited embed ids', () => {
    expect(normalizeEmbedIds(['c1', ' c2 ', '', 123])).toEqual(['c1', 'c2']);
    expect(normalizeEmbedIds('c1| c2 ||')).toEqual(['c1', 'c2']);
  });

  it('returns empty array for invalid values', () => {
    expect(normalizeEmbedIds(null)).toEqual([]);
    expect(normalizeEmbedIds({})).toEqual([]);
  });
});

describe('dedupeShareChatEmbeds', () => {
  it('keeps the first row for each embed id', () => {
    expect(dedupeShareChatEmbeds([
      { embed_id: 'parent', embed_ids: ['child'] },
      { embed_id: 'child', encrypted_content: 'first' },
      { embed_id: 'child', encrypted_content: 'duplicate' },
      { embed_id: 'other' }
    ])).toEqual([
      { embed_id: 'parent', embed_ids: ['child'] },
      { embed_id: 'child', encrypted_content: 'first' },
      { embed_id: 'other' }
    ]);
  });
});

describe('deriveParentByChildEmbeds', () => {
  it('derives child->parent mapping from embed_ids', () => {
    const map = deriveParentByChildEmbeds([
      { embed_id: 'parent', embed_ids: ['c1', 'c2'] },
      { embed_id: 'c1' },
      { embed_id: 'c2' }
    ]);

    expect(map.get('c1')).toBe('parent');
    expect(map.get('c2')).toBe('parent');
  });

  it('does not overwrite existing child mapping', () => {
    const map = deriveParentByChildEmbeds([
      { embed_id: 'p1', embed_ids: ['c'] },
      { embed_id: 'p2', embed_ids: ['c'] }
    ]);

    expect(map.get('c')).toBe('p1');
  });

  it('supports historical pipe-delimited embed_ids content', () => {
    const map = deriveParentByChildEmbeds([
      { embed_id: 'p1', embed_ids: 'c1|c2' },
      { embed_id: 'p2', embed_ids: [null, 123, '', 'ok'] as any }
    ]);

    expect(map.size).toBe(3);
    expect(map.get('c1')).toBe('p1');
    expect(map.get('c2')).toBe('p1');
    expect(map.get('ok')).toBe('p2');
  });
});
