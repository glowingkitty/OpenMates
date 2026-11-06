import { describe, expect, it } from 'vitest';
import { resolveReferenceableEmbedIds, type ReferencedEmbed } from './referenceableEmbeds';

const embeds: Record<string, ReferencedEmbed> = {
  'generate-parent': { type: 'app-skill-use', childEmbedIds: ['image-a', 'image-b'] },
  'view-skill': { type: 'app-skill-use', childEmbedIds: [] },
  'image-a': { type: 'generated_image', childEmbedIds: [] },
  'website-1': { type: 'website', childEmbedIds: [] },
};
const lookup = async (id: string) => embeds[id] ?? null;

describe('questionnaire referenceable embeds', () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('replaces an app-skill embed with its result children', async () => {
    expect(await resolveReferenceableEmbedIds(['generate-parent'], lookup)).toEqual(['image-a', 'image-b']);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('never references an app-skill embed that has no results', async () => {
    expect(await resolveReferenceableEmbedIds(['view-skill'], lookup)).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('keeps result and not-yet-synced embeds, in order and without duplicates', async () => {
    expect(await resolveReferenceableEmbedIds(['website-1', 'generate-parent', 'image-a', 'unsynced'], lookup))
      .toEqual(['website-1', 'image-a', 'image-b', 'unsynced']);
  });
});
