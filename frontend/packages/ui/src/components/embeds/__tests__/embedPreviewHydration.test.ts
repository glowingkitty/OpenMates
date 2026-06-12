// frontend/packages/ui/src/components/embeds/__tests__/embedPreviewHydration.test.ts
// Unit coverage for bounded embed preview hydration decisions.
// Large chat tests use synthetic carousel/child-id data only; these assertions
// must never trigger embed decryption, provider calls, or AI inference.
// Architecture: docs/specs/scalable-chat-embed-loading/spec.yml

import { describe, expect, it } from 'vitest';
import {
  buildImageSearchPreviewMetadata,
  buildWebSearchPreviewMetadata,
  getParentPreviewResultState,
  shouldHydrateCarouselSlide,
} from '../embedPreviewHydration';

describe('embed preview hydration bounds', () => {
  it('hydrates only active and adjacent carousel slides by default', () => {
    const hydrated = Array.from({ length: 20 }, (_, index) => index).filter((index) =>
      shouldHydrateCarouselSlide(8, index, 20),
    );

    expect(hydrated).toEqual([7, 8, 9]);
  });

  it('wraps carousel hydration at the run boundary', () => {
    const hydrated = Array.from({ length: 5 }, (_, index) => index).filter((index) =>
      shouldHydrateCarouselSlide(0, index, 5),
    );

    expect(hydrated).toEqual([0, 1, 4]);
  });

  it('does not expose helpers for preview-time child hydration', async () => {
    const helpers = await import('../embedPreviewHydration');

    expect(Object.keys(helpers)).not.toContain('limitLegacyPreviewChildIds');
  });

  it('does not treat legacy parents with child IDs as zero-result previews', () => {
    expect(getParentPreviewResultState({ status: 'finished', previewResultCount: 0, childEmbedIds: ['child-1'] })).toBe('missing_preview_metadata');
  });

  it('does not treat positive parent result counts without preview metadata as zero-result previews', () => {
    expect(getParentPreviewResultState({ status: 'finished', previewResultCount: 0, resultCount: 6 })).toBe('missing_preview_metadata');
  });

  it('only reports known zero results when the parent explicitly stores result_count zero', () => {
    expect(getParentPreviewResultState({ status: 'finished', previewResultCount: 0, resultCount: 0 })).toBe('known_zero_results');
  });

  it('builds allowlisted web search parent preview metadata only', () => {
    const metadata = buildWebSearchPreviewMetadata([
      {
        title: 'Result',
        url: 'https://example.com',
        favicon_url: 'https://example.com/favicon.ico',
        preview_image_url: 'https://example.com/preview.jpg',
        snippet: 'Short summary',
        description: 'full child description',
        extra_snippets: ['raw child snippet'],
      } as Parameters<typeof buildWebSearchPreviewMetadata>[0][number] & {
        description: string;
        extra_snippets: string[];
      },
    ]);

    expect(metadata).toEqual({
      result_count: 1,
      preview_results: [
        {
          title: 'Result',
          url: 'https://example.com',
          favicon: undefined,
          favicon_url: 'https://example.com/favicon.ico',
          meta_url: undefined,
          preview_image_url: 'https://example.com/preview.jpg',
          snippet: 'Short summary',
        },
      ],
    });
    expect(JSON.stringify(metadata)).not.toContain('full child description');
    expect(JSON.stringify(metadata)).not.toContain('raw child snippet');
  });

  it('limits image parent preview metadata and mirrors JSON payload', () => {
    const results = Array.from({ length: 8 }, (_, index) => ({
      title: `Image ${index}`,
      source_page_url: `https://example.com/${index}`,
      image_url: `https://cdn.example.com/${index}.jpg`,
      thumbnail_url: `https://cdn.example.com/${index}-thumb.jpg`,
      source: 'example.com',
      favicon_url: 'https://example.com/favicon.ico',
      raw_provider_payload: { hidden: true },
    })) as Array<Parameters<typeof buildImageSearchPreviewMetadata>[0][number] & { raw_provider_payload: { hidden: boolean } }>;

    const metadata = buildImageSearchPreviewMetadata(results);

    expect(metadata.result_count).toBe(8);
    expect(metadata.preview_results).toHaveLength(6);
    expect(metadata.preview_results_json).toBe(JSON.stringify(metadata.preview_results));
    expect(JSON.stringify(metadata)).not.toContain('raw_provider_payload');
  });
});
