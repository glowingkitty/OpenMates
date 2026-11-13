import { describe, expect, it } from 'vitest';
import { isEmbedUuid, resolveReferenceableEmbedIds, type ReferencedEmbed } from './referenceableEmbeds';

const GENERATE_PARENT = '11111111-1111-4111-8111-111111111111';
const VIEW_SKILL = '22222222-2222-4222-8222-222222222222';
const IMAGE_A = '90e9b475-2601-4aaa-8aaa-aaaaaaaaaaaa';
const IMAGE_B = '6f165aae-a4cc-4bbb-8bbb-bbbbbbbbbbbb';
const WEBSITE = '33333333-3333-4333-8333-333333333333';
const UNSYNCED = '44444444-4444-4444-8444-444444444444';

const embeds: Record<string, ReferencedEmbed> = {
  [GENERATE_PARENT]: { type: 'app-skill-use', childEmbedIds: [IMAGE_A, IMAGE_B] },
  [VIEW_SKILL]: { type: 'app-skill-use', childEmbedIds: [] },
  [IMAGE_A]: { type: 'generated_image', childEmbedIds: [] },
  [WEBSITE]: { type: 'website', childEmbedIds: [] },
};
const lookedUp: string[] = [];
const lookup = async (id: string) => { lookedUp.push(id); return embeds[id] ?? null; };
const refs: Record<string, string> = { 'generated-images-90e9b4752601': IMAGE_A };
const resolveRef = async (ref: string) => refs[ref] ?? null;

describe('questionnaire referenceable embeds', () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('replaces an app-skill embed with its result children', async () => {
    expect(await resolveReferenceableEmbedIds([GENERATE_PARENT], lookup, resolveRef)).toEqual([IMAGE_A, IMAGE_B]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('never references an app-skill embed that has no results', async () => {
    expect(await resolveReferenceableEmbedIds([VIEW_SKILL], lookup, resolveRef)).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('keeps result and not-yet-synced embeds, in order and without duplicates', async () => {
    expect(await resolveReferenceableEmbedIds([WEBSITE, GENERATE_PARENT, IMAGE_A, UNSYNCED], lookup, resolveRef))
      .toEqual([WEBSITE, IMAGE_A, IMAGE_B, UNSYNCED]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('maps an embed_ref slug written by the model to its embed ID (issue 4KC3C)', async () => {
    expect(await resolveReferenceableEmbedIds(['generated-images-90e9b4752601', IMAGE_A], lookup, resolveRef))
      .toEqual([IMAGE_A]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('keeps an unmapped slug without looking it up by ID on the server', async () => {
    lookedUp.length = 0;
    expect(await resolveReferenceableEmbedIds(['generated-images-6f165aaea4cc'], lookup, resolveRef))
      .toEqual(['generated-images-6f165aaea4cc']);
    expect(lookedUp).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('distinguishes embed IDs from embed_ref slugs', () => {
    expect(isEmbedUuid(IMAGE_A)).toBe(true);
    expect(isEmbedUuid('generated-images-90e9b4752601')).toBe(false);
  });
});
