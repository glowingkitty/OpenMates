import { describe, expect, it } from 'vitest';
import { getFitnessResultImageUrl, getFitnessResultFacts, normalizeFitnessSearchContent } from '../fitnessEmbedData';
import searchFixture, { variants as searchVariants } from '../FitnessSearchEmbedFullscreen.preview';

describe('fitness provider image preservation', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('exercises class precedence, venue fallback and absence in the actual fullscreen search fixture', () => {
    const results = normalizeFitnessSearchContent(searchFixture.data.decodedContent).results;
    expect(results).toHaveLength(2);
    expect(getFitnessResultImageUrl(results[0])).toBe('/preview-fixtures/fitness-yoga-studio.svg');
    expect(getFitnessResultImageUrl(results[1])).toBe('/preview-fixtures/fitness-hiit-studio.svg');
    expect(normalizeFitnessSearchContent(searchVariants.noImage.data.decodedContent).results.map(getFitnessResultImageUrl)).toEqual(['', '']);
  });
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

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
describe('supplied fitness facts', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('retains singular discipline, instructor, numeric spots, duration and explicit currency', () => {
    expect(getFitnessResultFacts({discipline:'Yoga',instructor:'Alex',spots_left:3,duration_minutes:45,price:12,currency:'GBP'}))
      .toEqual({disciplines:['Yoga'],instructor:'Alex',spots:'3',durationMinutes:45,price:12,currency:'GBP'});
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
  it('preserves zero without manufacturing a currency or translating it into free availability', () => {
    expect(getFitnessResultFacts({spots_left:0,duration_minutes:0,price:0})).toMatchObject({spots:'0',durationMinutes:0,price:0,currency:''});
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
  it('keeps blanks, malformed and missing numbers unknown', () => {
    expect(getFitnessResultFacts({spots_left:' ',duration_minutes:'',price:false,instructor:{}}))
      .toEqual({disciplines:[],instructor:'',spots:'',durationMinutes:undefined,price:undefined,currency:''});
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('retains legacy spots presentation and plural disciplines alongside supplied aliases', () => {
    expect(getFitnessResultFacts({spots_display:'2 remaining',spots_left:2,disciplines:'Yoga|Pilates',discipline:'Yoga'}))
      .toMatchObject({spots:'2 remaining',disciplines:['Yoga','Pilates']});
  });
});
