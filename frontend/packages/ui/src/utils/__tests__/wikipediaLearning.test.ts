// contract-test-file: supporting surface=gui.web assertions=wikipedia-mentions.links.name-consistency
import { describe, it, expect } from 'vitest';
import { wikipediaNameMatches, wikipediaArticleIdentity } from '../wikipediaLearning';

describe('Wikipedia topic identity', () => {
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.links.name-consistency
  it('accepts space, underscore, case and Unicode formatting differences', () => {
    expect(wikipediaNameMatches('Ada Lovelace', 'Ada_Lovelace')).toBe(true);
    expect(wikipediaNameMatches('Ａｄａ Lovelace', 'ada_lovelace')).toBe(true);
    expect(wikipediaNameMatches('Mercury', 'Mercury_(planet)')).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.links.name-consistency
  it('rejects aliases, broader topics and empty names', () => {
    expect(wikipediaNameMatches('Einstein', 'Albert_Einstein')).toBe(false);
    expect(wikipediaNameMatches('Fraction', 'Mathematics')).toBe(false);
    expect(wikipediaNameMatches('', '')).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.links.name-consistency
  it('retains the selected article language in its canonical source URL', () => {
    expect(wikipediaArticleIdentity('Ada_Lovelace', 'de')).toEqual({
      canonical_title: 'Ada Lovelace', language: 'de', source_url: 'https://de.wikipedia.org/wiki/Ada_Lovelace',
    });
  });
});
