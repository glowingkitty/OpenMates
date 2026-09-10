/**
 * Focused unit coverage for shared search result image selection.
 * Run with node --test --experimental-strip-types.
 * Covers legacy news fields, normalized metadata, and bounded deduplication.
 * No network or product stack is used.
 * Architecture: docs/architecture/embeds.md
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { searchResultImageUrl, searchPreviewImages } from './searchPreviewImages.ts';

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('recognizes image, web and flattened or nested news thumbnails', () => {
  for (const result of [
    { thumbnail_url: 'https://example.org/image.jpg' },
    { image_url: 'https://example.org/image.jpg' },
    { preview_image_url: 'https://example.org/image.jpg' },
    { thumbnail_original: 'https://example.org/image.jpg' },
    { thumbnail_src: 'https://example.org/image.jpg' },
    { thumbnail: { original: 'https://example.org/image.jpg' } },
    { thumbnail: { src: 'https://example.org/image.jpg' } },
  ]) assert.equal(searchResultImageUrl(result), 'https://example.org/image.jpg');
});

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('rejects missing image values without treating favicons as article images', () => {
  for (const result of [null, undefined, {}, { favicon: 'icon.png' },
    { image_url: 42 }, { thumbnail: null }, { thumbnail_url: ' ' }]) {
    assert.equal(searchResultImageUrl(result), undefined);
  }
});

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('deduplicates before applying the thumbnail cap and preserves titles', () => {
  const results = Array.from({ length: 20 }, (_, index) => ({
    image_url: `https://example.org/${index}.jpg`, title: `Image ${index}`,
  }));
  const images = searchPreviewImages([results[0], ...results]);
  assert.equal(images.length, 10);
  assert.deepEqual(images[0], { url: results[0].image_url, title: 'Image 0' });
  assert.equal(images[9].url, results[9].image_url);
});
