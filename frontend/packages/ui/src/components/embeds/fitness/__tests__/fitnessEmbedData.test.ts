import { describe, expect, it } from 'vitest';
import { getFitnessResultImageUrl, normalizeFitnessSearchContent } from '../fitnessEmbedData';

describe('fitness provider image preservation', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('keeps class imagery ahead of an organizing venue fallback', () => {
    expect(getFitnessResultImageUrl({ class_image_url: 'https://storage.googleapis.com/usc/class.jpg', image_url: 'https://storage.googleapis.com/usc/venue.jpg' }))
      .toBe('https://storage.googleapis.com/usc/class.jpg');
    expect(getFitnessResultImageUrl({ venue_image_url: 'https://storage.googleapis.com/usc/venue.jpg' }))
      .toBe('https://storage.googleapis.com/usc/venue.jpg');
    expect(getFitnessResultImageUrl({ image_url: 'https://storage.googleapis.com/usc/canonical.jpg', venue_image_url: 'https://storage.googleapis.com/usc/venue.jpg' }))
      .toBe('https://storage.googleapis.com/usc/canonical.jpg');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('does not manufacture an image for absent or malformed provider media', () => {
    expect(getFitnessResultImageUrl({})).toBe('');
    expect(getFitnessResultImageUrl({ image_url: '  ', venue_image_url: null })).toBe('');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('retains provider image fields through flat and grouped search envelopes', () => {
    const result = { id: 'class-1', image_url: 'https://storage.googleapis.com/usc/class.jpg', venue_image_url: 'https://storage.googleapis.com/usc/venue.jpg' };
    for (const payload of [{ results: [result] }, { results: [{ results: [result], result_count: 1 }] }]) {
      const normalized = normalizeFitnessSearchContent(payload);
      expect(normalized.results[0]).toMatchObject(result);
      expect(getFitnessResultImageUrl(normalized.results[0])).toBe(result.image_url);
    }
  });
});
