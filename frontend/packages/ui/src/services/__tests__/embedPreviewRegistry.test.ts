// frontend/packages/ui/src/services/__tests__/embedPreviewRegistry.test.ts
// Contract tests for parent metadata propagation through the preview registry.
// These assertions keep metadata-only parent embeds useful without forcing
// preview-time child hydration or provider calls.

import { describe, expect, it } from 'vitest';
import { embedPreviewRegistry, parentPreviewProps } from '../embedPreviewRegistry';

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
  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('resolves Finance check_accounts app skill previews', () => {
    expect(embedPreviewRegistry.canResolve({
      embedId: 'finance-preview',
      embedData: { type: 'app_skill_use', app_id: 'finance', skill_id: 'check_accounts' },
      decodedContent: { app_id: 'finance', skill_id: 'check_accounts' },
    })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
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

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
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

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
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

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('resolves raw travel connection children before their inherited parent skill', async () => {
    const resolved = await embedPreviewRegistry.resolve({
      embedId: 'connection-child',
      embedData: {
        type: 'connection',
        status: 'finished',
        app_id: 'travel',
        skill_id: 'search_connections',
      },
      decodedContent: {
        type: 'connection',
        app_id: 'travel',
        skill_id: 'search_connections',
        total_price: '636',
        currency: 'EUR',
        origin: 'Berlin (BER)',
        destination: 'Bangkok (BKK)',
        departure: '2026-04-14T10:00:00Z',
        arrival: '2026-04-15T06:20:00Z',
        duration: '15h 20m',
        stops: 1,
      },
      onFullscreen: () => {},
    });

    expect(resolved?.props).toMatchObject({
      price: '636',
      currency: 'EUR',
      origin: 'Berlin (BER)',
      destination: 'Bangkok (BKK)',
      duration: '15h 20m',
      stops: 1,
    });
    expect(resolved?.props).not.toHaveProperty('resultCount');
    expect(resolved?.props).not.toHaveProperty('childEmbedIds');
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('resolves raw Maps place children before their inherited parent skill', async () => {
    const resolved = await embedPreviewRegistry.resolve({
      embedId: 'place-child',
      embedData: {
        type: 'place',
        status: 'finished',
        app_id: 'maps',
        skill_id: 'search',
      },
      decodedContent: {
        type: 'place_result',
        app_id: 'maps',
        skill_id: 'search',
        name: 'St. Oberholz',
        formatted_address: 'Rosenthaler Str. 72A, Berlin',
        rating: 3.8,
        user_rating_count: 1941,
        image_url: 'https://example.com/st-oberholz.jpg',
      },
      onFullscreen: () => {},
    });

    expect(resolved?.props).toMatchObject({
      displayName: 'St. Oberholz',
      formattedAddress: 'Rosenthaler Str. 72A, Berlin',
      rating: 3.8,
      userRatingCount: 1941,
      imageUrl: 'https://example.com/st-oberholz.jpg',
    });
    expect(resolved?.props).not.toHaveProperty('query');
    expect(resolved?.props).not.toHaveProperty('results');
  });
});
