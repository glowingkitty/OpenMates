// Spec: app-memories.references.embeds
import { describe, expect, it } from 'vitest';
import {
  bodyToDocument, bodyWithLegacyReferences, documentToBody, embedIdsInBody, referencesFromBody,
} from '../memoryBodyDocument';

const fence = (id: string, type = 'website') => `\`\`\`json\n${JSON.stringify({ type, embed_id: id, reference_only: true }, null, 2)}\n\`\`\``;

describe('memory body document', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('round-trips plain text exactly, including blank lines and Markdown characters', () => {
    for (const body of ['', 'one line', '- a\n- b', 'a\n\nb\n', '# Heading\n**bold** and `code`']) {
      expect(documentToBody(bodyToDocument(body))).toBe(body);
    }
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('turns inline embed blocks into embed nodes between the surrounding text', () => {
    const body = `Intro\n${fence('abc')}\nOutro`;
    const doc = bodyToDocument(body);
    expect(doc.content.map((node) => node.type)).toEqual(['paragraph', 'paragraph', 'paragraph']);
    const embed = doc.content[1].content?.[0];
    expect(embed?.attrs?.contentRef).toBe('embed:abc');
    expect(embed?.attrs?.referenceOnly).toBe(true);
    expect(documentToBody(doc)).toBe(body);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('forces reference-only so removing a block never deletes the embed', () => {
    const body = `\`\`\`json\n${JSON.stringify({ type: 'website', embed_id: 'abc' })}\n\`\`\``;
    expect(bodyToDocument(body).content[0].content?.[0]?.attrs?.referenceOnly).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('derives the reference list from the embed blocks, once each, in order', () => {
    const body = `${fence('a')}\ntext\n${fence('b')}\n${fence('a')}\n\`\`\`json\n{"hello":1}\n\`\`\``;
    expect(embedIdsInBody(body)).toEqual(['a', 'b']);
    expect(referencesFromBody(body)).toEqual([{ kind: 'embed', id: 'a' }, { kind: 'embed', id: 'b' }]);
    expect(referencesFromBody('no embeds')).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.references.embeds
  it('shows references saved in the old separate list as inline embeds', async () => {
    const types: Record<string, string | null> = { old: 'website', gone: null };
    const body = await bodyWithLegacyReferences('Text', [
      { kind: 'embed', id: 'old' }, { kind: 'embed', id: 'gone' }, { kind: 'embed', id: 'present' },
    ], async (id) => types[id] ?? null);
    expect(embedIdsInBody(body)).toEqual(['old']);
    expect(body.startsWith('Text\n```json')).toBe(true);
    expect(await bodyWithLegacyReferences(`${fence('old')}`, [{ kind: 'embed', id: 'old' }], async () => 'website')).toBe(fence('old'));
  });
});
