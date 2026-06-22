// frontend/packages/ui/src/services/__tests__/embedPreviewRegistry.test.ts
// Contract tests for parent metadata propagation through the preview registry.
// These assertions keep metadata-only parent embeds useful without forcing
// preview-time child hydration or provider calls.

import { describe, expect, it } from 'vitest';
import { parentPreviewProps } from '../embedPreviewRegistry';

function metadataFor(decodedContent: Record<string, unknown>) {
  return parentPreviewProps(
    {
      status: 'finished',
      query: 'search query',
      provider: 'Brave Search',
      result_count: 2,
      embed_ids: ['child-1', 'child-2'],
      ...decodedContent,
    },
    { embed_ids: ['child-from-embed-data'] },
  );
}

describe('embedPreviewRegistry parent preview metadata', () => {
  it('forwards web search parent metadata', async () => {
    const metadata = metadataFor({
      preview_results: [{ title: 'OpenMates', url: 'https://openmates.org', favicon: 'https://openmates.org/favicon.svg' }],
    });

    expect(metadata).toMatchObject({
      results: [{ title: 'OpenMates', url: 'https://openmates.org', favicon: 'https://openmates.org/favicon.svg' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });

  it('forwards image search parent preview JSON and children', async () => {
    const previewResults = [{ title: 'Image', thumbnail_url: 'https://example.com/thumb.jpg' }];
    const metadata = metadataFor({
      preview_results: previewResults,
      preview_results_json: JSON.stringify(previewResults),
    });

    expect(metadata).toMatchObject({
      results: previewResults,
      previewResultsJson: JSON.stringify(previewResults),
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });

  it('forwards news and videos search preview metadata instead of empty results', async () => {
    const newsMetadata = metadataFor({
      preview_results: [{ title: 'News', url: 'https://news.example', favicon: 'https://news.example/favicon.ico' }],
    });
    const videosMetadata = metadataFor({
      preview_results: [{ title: 'Video', url: 'https://video.example', meta_url_profile_image: 'https://video.example/avatar.jpg' }],
    });

    expect(newsMetadata).toMatchObject({
      results: [{ title: 'News', url: 'https://news.example', favicon: 'https://news.example/favicon.ico' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
    expect(videosMetadata).toMatchObject({
      results: [{ title: 'Video', url: 'https://video.example', meta_url_profile_image: 'https://video.example/avatar.jpg' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });
});
