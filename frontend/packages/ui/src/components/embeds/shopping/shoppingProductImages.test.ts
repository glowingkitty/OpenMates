import { describe, expect, it } from 'vitest';
import { normalizeShoppingProductImages } from './shoppingProductImages';

describe('supplied shopping product galleries', () => {
  // contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
  it('preserves order and deduplicates arrays and TOON scalars', () => {
    expect(normalizeShoppingProductImages([' front ', null, 'back', 'back', '', 'detail'], 'front'))
      .toEqual(['front', 'back', 'detail']);
    expect(normalizeShoppingProductImages(' front |back|back||detail ', 'front'))
      .toEqual(['front', 'back', 'detail']);
  });
  // contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
  it('retains primary-only products and missing photos without inventing URLs', () => {
    expect(normalizeShoppingProductImages(undefined, ' primary ')).toEqual(['primary']);
    expect(normalizeShoppingProductImages([], null)).toEqual([]);
    expect(normalizeShoppingProductImages(42)).toEqual([]);
    expect(normalizeShoppingProductImages(['back'], 'front')).toEqual(['front', 'back']);
    expect(normalizeShoppingProductImages(['back', 'front'], 'front')).toEqual(['back', 'front']);
  });
});
