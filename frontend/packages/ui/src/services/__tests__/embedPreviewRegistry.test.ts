// frontend/packages/ui/src/services/__tests__/embedPreviewRegistry.test.ts
// Contract tests for parent metadata propagation through the preview registry.
// These assertions keep metadata-only parent embeds useful without forcing
// preview-time child hydration or provider calls.

import { describe, expect, it } from 'vitest';
import { embedPreviewRegistry, type EmbedPreviewContext } from '../embedPreviewRegistry';

function contextFor(
  appId: string,
  skillId: string,
  decodedContent: Record<string, unknown>,
): EmbedPreviewContext {
  return {
    embedId: `${appId}-${skillId}-parent`,
    embedData: {
      status: 'finished',
      app_id: appId,
      skill_id: skillId,
      embed_ids: ['child-from-embed-data'],
    },
    decodedContent: {
      app_id: appId,
      skill_id: skillId,
      status: 'finished',
      query: `${appId} query`,
      provider: 'Brave Search',
      result_count: 2,
      embed_ids: ['child-1', 'child-2'],
      ...decodedContent,
    },
    onFullscreen: () => {},
  };
}

describe('embedPreviewRegistry parent preview metadata', () => {
  it('forwards web search parent metadata', async () => {
    const resolved = await embedPreviewRegistry.resolve(contextFor('web', 'search', {
      preview_results: [{ title: 'OpenMates', url: 'https://openmates.org', favicon: 'https://openmates.org/favicon.svg' }],
    }));

    expect(resolved?.props).toMatchObject({
      results: [{ title: 'OpenMates', url: 'https://openmates.org', favicon: 'https://openmates.org/favicon.svg' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });

  it('forwards image search parent preview JSON and children', async () => {
    const previewResults = [{ title: 'Image', thumbnail_url: 'https://example.com/thumb.jpg' }];
    const resolved = await embedPreviewRegistry.resolve(contextFor('images', 'search', {
      preview_results: previewResults,
      preview_results_json: JSON.stringify(previewResults),
    }));

    expect(resolved?.props).toMatchObject({
      results: previewResults,
      previewResultsJson: JSON.stringify(previewResults),
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });

  it('forwards news and videos search preview metadata instead of empty results', async () => {
    const newsResolved = await embedPreviewRegistry.resolve(contextFor('news', 'search', {
      preview_results: [{ title: 'News', url: 'https://news.example', favicon: 'https://news.example/favicon.ico' }],
    }));
    const videosResolved = await embedPreviewRegistry.resolve(contextFor('videos', 'search', {
      preview_results: [{ title: 'Video', url: 'https://video.example', meta_url_profile_image: 'https://video.example/avatar.jpg' }],
    }));

    expect(newsResolved?.props).toMatchObject({
      results: [{ title: 'News', url: 'https://news.example', favicon: 'https://news.example/favicon.ico' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
    expect(videosResolved?.props).toMatchObject({
      results: [{ title: 'Video', url: 'https://video.example', meta_url_profile_image: 'https://video.example/avatar.jpg' }],
      resultCount: 2,
      childEmbedIds: ['child-1', 'child-2'],
    });
  });
});
