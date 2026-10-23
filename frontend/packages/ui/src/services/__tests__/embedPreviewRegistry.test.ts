// frontend/packages/ui/src/services/__tests__/embedPreviewRegistry.test.ts
// Contract tests for parent metadata propagation through the preview registry.
// These assertions keep metadata-only parent embeds useful without forcing
// preview-time child hydration or provider calls.

import { describe, expect, it, vi } from 'vitest';

// These unit checks verify renderer selection and its props. The real Svelte
// components are exercised by the bare preview and route E2E specs; importing
// their authentication/runtime graph here would obscure that small contract.
const previews = vi.hoisted(() => ({ website: () => {}, news: () => {}, connection: () => {}, place: () => {}, search: () => {}, event: () => {} }));
vi.mock('../../components/embeds/web/WebSearchEmbedPreview.svelte', () => ({ default: previews.search }));
vi.mock('../../components/embeds/news/NewsEmbedPreview.svelte', () => ({ default: previews.news }));
vi.mock('../../components/embeds/web/WebsiteEmbedPreview.svelte', () => ({ default: previews.website }));
vi.mock('../../components/embeds/travel/TravelConnectionEmbedPreview.svelte', () => ({ default: previews.connection }));
vi.mock('../../components/embeds/maps/MapLocationEmbedPreview.svelte', () => ({ default: previews.place }));
vi.mock('../../components/embeds/events/EventEmbedPreview.svelte', () => ({ default: previews.event }));
import { embedPreviewRegistry, parentPreviewProps, pdfPreviewProps } from '../embedPreviewRegistry';
import connectionFixture, { variants as connectionVariants } from '../../components/embeds/travel/TravelConnectionEmbedPreview.preview';

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
  // contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.output.source-and-identity
  it.each([
    [{ type: 'place_result', types: ['cafe', 'food', 'establishment'] }, 'Cafe'],
    [{ type: 'place_result', types: 'coffee_shop|food|establishment' }, 'Coffee shop'],
    [{ type: 'place_result', place_type: 'Ruins', types: ['establishment'] }, 'Ruins'],
    [{ type: 'place_result', place_type: 'place_result', types: ['cafe'] }, 'Cafe'],
    [{ type: 'place_result', types: ['point_of_interest', 'establishment'] }, undefined],
  ])('uses place categories without exposing the embed discriminator: %j', async (content, label) => {
    const resolved = await embedPreviewRegistry.resolve({
      embedId: 'place-label-regression', embedData: { type: 'maps-place', status: 'finished', app_id: 'maps', skill_id: 'search' },
      decodedContent: { name: 'Evening Coffee', ...content }, onFullscreen: () => {},
    });
    expect(resolved?.props.__previewComponent).toBe(previews.place);
    expect(resolved?.props.placeType).toBe(label);
    expect(resolved?.props.displayName).toBe('Evening Coffee');
  });
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  it('keeps flat and nested one-way preview journeys consistent across flight and rail examples', () => {
    for (const fixture of [connectionFixture, connectionVariants.multiStop, connectionVariants.deutscheBahn,
      connectionVariants.flixTrain, connectionVariants.trainRealtime]) {
      const legs = fixture.connection?.legs;
      if (!legs?.length) continue; // Legacy flat payloads must not inherit another journey's nested data.
      expect(legs).toHaveLength(1);
      expect(legs[0]).toMatchObject({ origin: fixture.origin, destination: fixture.destination,
        departure: fixture.departure, arrival: fixture.arrival });
    }
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it('shows the request query for an older saved parent using the CLI requests envelope', async () => {
    const resolved = await embedPreviewRegistry.resolve({
      embedId: 'saved-parent', embedData: { type: 'app_skill_use', status: 'finished' },
      decodedContent: { app_id: 'web', skill_id: 'search', input: { requests: [{ query: 'Saved native request' }] }, result_count: 10, embed_ids: ['child'] },
      onFullscreen: () => {},
    });
    expect(resolved?.props.__previewComponent).toBe(previews.search);
    expect(resolved?.props.__previewPresentation).toBe('execution');
    expect(resolved?.props).toMatchObject({ query: 'Saved native request', resultCount: 10, childEmbedIds: ['child'] });
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  it('renders website children with their own metadata instead of the inherited search parent', async () => {
    const onFullscreen = () => {};
    for (const type of ['website', 'web-website', 'search_result']) {
      const resolved = await embedPreviewRegistry.resolve({
        embedId: 'website-child',
        embedData: { type, status: 'finished', app_id: 'web', skill_id: 'search' },
        decodedContent: { app_id: 'web', skill_id: 'search', url: 'https://example.test', title: 'Saved website', snippet: 'Website snippet', meta_url: { favicon: 'https://example.test/icon.png' }, thumbnail: { original: 'https://example.test/photo.png' } },
        onFullscreen,
      });
      expect(resolved?.props.__previewComponent).toBe(previews.website);
      expect(resolved?.props.__previewPresentation).toBe('content');
      expect(resolved?.props).toMatchObject({ id: 'website-child', url: 'https://example.test', title: 'Saved website', description: 'Website snippet', favicon: 'https://example.test/icon.png', image: 'https://example.test/photo.png', status: 'finished', onFullscreen });
      expect(resolved?.props).not.toHaveProperty('childEmbedIds');
      expect(resolved?.props).not.toHaveProperty('resultCount');
    }
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  it.each(['website', 'web-website', 'search_result'])('keeps News article identity and metadata for %s children', async (type) => {
    const onFullscreen = vi.fn();
    const resolved = await embedPreviewRegistry.resolve({
      embedId: 'news-child-2', embedData: { type, status: 'finished', app_id: 'news', skill_id: 'search' },
      decodedContent: { app_id: 'news', skill_id: 'search', parent_embed_id: 'news-root', url: 'https://example.test/article-2', title: 'Second article', snippet: 'Article details', thumbnail: { original: 'https://example.test/photo.png' } },
      onFullscreen,
    });
    expect(resolved?.props.__previewComponent).toBe(previews.news);
    expect(resolved?.props.__previewPresentation).toBe('content');
    expect(resolved?.props).toMatchObject({ id: 'news-child-2', url: 'https://example.test/article-2', title: 'Second article', description: 'Article details', image: 'https://example.test/photo.png' });
    (resolved?.props.onFullscreen as () => void)();
    expect(onFullscreen).toHaveBeenCalledOnce();
  });

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

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity,travel-search.realtime.source-faithful
  it('retains nested travel route and realtime metadata in Apps result previews', async () => {
    const connection = { app_id: 'travel', skill_id: 'search_connections', legs: [{
      origin: 'Berlin', destination: 'Hamburg', departure: '2026-12-15T08:00:00Z', arrival: '2026-12-15T10:00:00Z',
      segments: [{ arrival_delay_minutes: 12, cancelled: true }],
    }] };
    const resolved = await embedPreviewRegistry.resolve({ embedId: 'nested-rail', embedData: { type: 'connection', status: 'finished' }, decodedContent: connection, onFullscreen: () => {} });
    expect(resolved?.props.__previewComponent).toBe(previews.connection);
    expect(resolved?.props.__previewPresentation).toBe('content');
    expect(resolved?.props).toMatchObject({ connection, origin: 'Berlin', destination: 'Hamburg', departure: '2026-12-15T08:00:00Z', arrival: '2026-12-15T10:00:00Z', arrivalDelayMinutes: 12, hasCancellation: true });
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

// contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
it('normalizes backend child types through the central embed mapping', () => {
  for (const type of ['event', 'event_result', 'events-event']) {
    expect(embedPreviewRegistry.canResolve({
      embedId: 'event-child', embedData: { type }, decodedContent: {},
    })).toBe(true);
  }
});

// contract-test: supporting surface=gui.web assertions=projects.items.responsive-embeds
it('registers existing captured files for shared preview rendering', () => {
  expect(embedPreviewRegistry.canResolve({
    embedId: 'captured-file',
    embedData: { type: 'file-file', status: 'finished' },
    decodedContent: {
      filename: 'report.pdf',
      path: 'output/report.pdf',
      mime_type: 'application/pdf',
      size_bytes: 2048,
    },
  })).toBe(true);
});

// contract-test: supporting surface=gui.web assertions=projects.items.responsive-embeds
it('resolves uploaded project PDFs through the existing PDF preview', () => {
  const onFullscreen = () => {};
  const embedData = { type: 'pdf', status: 'finished' };
  const decodedContent = {
    type: 'pdf',
    app_id: 'pdf',
    skill_id: 'upload',
    filename: 'architecture.pdf',
    file_type: 'application/pdf',
    file_size: 184_320,
    page_count: 12,
  };

  expect(embedPreviewRegistry.canResolve({
    embedId: 'project-pdf',
    embedData,
    decodedContent,
  })).toBe(true);
  expect(pdfPreviewProps('project-pdf', decodedContent, embedData, onFullscreen)).toMatchObject({
    id: 'project-pdf',
    filename: 'architecture.pdf',
    pageCount: 12,
    status: 'finished',
    isMobile: false,
    onFullscreen,
  });
});

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
it('normalizes flattened event child data through the shared registry', async () => {
  const resolved = await embedPreviewRegistry.resolve({ embedId: 'flat-event', embedData: { type: 'event', status: 'finished', app_id: 'events', skill_id: 'search' },
    decodedContent: { organizer_name: 'Berlin Lingua Hub', venue_name: 'Community space', fee_amount: '0', fee_currency: 'EUR', rsvp_count: '80', date_start: '2026-12-15T18:00:00Z', timezone: 'Europe/Berlin' }, onFullscreen: () => {},
  });
  expect(resolved?.props.__previewComponent).toBe(previews.event);
  expect(resolved?.props.__previewPresentation).toBe('content');
  expect(resolved?.props.event).toMatchObject({ embed_id: 'flat-event', organizer: {name: 'Berlin Lingua Hub'}, venue: {name: 'Community space'}, fee: {amount: 0, currency: 'EUR'}, rsvp_count: 80, date_start: '2026-12-15T18:00:00Z', timezone: 'Europe/Berlin' });
});
