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

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('accepts legacy string thumbnails and image aliases used by news fullscreen', () => {
  for (const result of [
    { thumbnail: 'https://example.org/photo.jpg' },
    { image: 'https://example.org/photo.jpg' },
    { 'thumbnail.src': 'https://example.org/photo.jpg' },
    { thumbnail_original: 'null', thumbnail_src: 'https://example.org/photo.jpg' },
  ]) assert.equal(searchResultImageUrl(result), 'https://example.org/photo.jpg');
});

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('legacy previews resolve bounded children but current parent images need no child reads', async () => {
  const { resolveSearchPreviewImages } = await import('./searchPreviewImages.ts');
  const reads = [];
  const loader = async id => { reads.push(id); return { thumbnail_src: `https://example.org/${id}.jpg` }; };
  const current = await resolveSearchPreviewImages([{ preview_image_url: 'https://example.org/current.jpg' }], ['unused'], loader);
  assert.equal(current[0].url, 'https://example.org/current.jpg');
  assert.deepEqual(reads, []);
  const ids = Array.from({ length: 20 }, (_, i) => String(i));
  const legacy = await resolveSearchPreviewImages([{ favicon: 'icon.png' }], [ids[0], ...ids], loader);
  assert.equal(legacy.length, 10);
  assert.deepEqual(reads, ids.slice(0, 10));
});

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('obsolete legacy-preview loads do not publish images', async () => {
  const { resolveSearchPreviewImages } = await import('./searchPreviewImages.ts');
  const controller = new AbortController();
  const images = await resolveSearchPreviewImages([], ['child'], async () => {
    controller.abort();
    return { thumbnail_src: 'https://example.org/old.jpg' };
  }, controller.signal);
  assert.deepEqual(images, []);
});

// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
test('web fullscreen and both search parents retain the shared image path', async () => {
  const { readFile } = await import('node:fs/promises');
  const source = name => readFile(new URL(`../components/embeds/${name}.svelte`, import.meta.url), 'utf8');
  const website = await source('web/WebsiteEmbedFullscreen');
  assert.match(website, /searchResultImageUrl\(dc\)/);
  assert.match(website, /searchResultImageUrl\(attrs\)/);
  for (const app of ['web', 'news']) {
    const parent = await source(`${app}/${app === 'web' ? 'Web' : 'News'}SearchEmbedPreview`);
    assert.match(parent, /<SearchThumbnailStrip[^>]*\{childEmbedIds\}/);
  }
  const search = await source('web/WebSearchEmbedFullscreen');
  assert.match(search, /searchResultImageUrl\(content\)/);
  assert.match(search, /searchResultImageUrl\(r\)/);
});
