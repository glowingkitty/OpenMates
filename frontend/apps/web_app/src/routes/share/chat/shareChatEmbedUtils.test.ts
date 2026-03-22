import { describe, expect, it } from 'vitest';
import { deriveParentByChildEmbeds } from './shareChatEmbedUtils';

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

  it('ignores invalid embed_ids content', () => {
    const map = deriveParentByChildEmbeds([
      { embed_id: 'p1', embed_ids: 'not-an-array' as any },
      { embed_id: 'p2', embed_ids: [null, 123, '', 'ok'] as any }
    ]);

    expect(map.size).toBe(1);
    expect(map.get('ok')).toBe('p2');
  });
});

