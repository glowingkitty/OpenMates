<!--
  frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedFullscreen.svelte

  Fullscreen view for Maps Search skill embeds.
  Uses UnifiedEmbedFullscreen plus EmbedsMapView so parent search results keep
  the standard embed fullscreen chrome while places are selected in-place.

  Displays:
  - Interactive map with markers for all place results
  - Scrollable list of place cards from EmbedsMapView
  - No nested child fullscreen when selecting a result

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedsMapView from '../EmbedsMapView.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  interface MapsFilterSummary {
    required?: unknown;
    candidate_count?: number;
    verified_count?: number;
    status?: string;
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : undefined;
  }

  function firstMapsGroup(content: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
    if (!content) return undefined;
    if (content.filter_summary || content.warnings) return content;
    const groups = Array.isArray(content.results) ? content.results : [];
    const firstGroup = asRecord(groups[0]);
    return firstGroup?.filter_summary || firstGroup?.warnings ? firstGroup : content;
  }

  function stringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [];
  }

  function hasEmbedRefs(value: unknown): boolean {
    if (Array.isArray(value)) return value.some((item) => typeof item === 'string' && item.trim().length > 0);
    return typeof value === 'string' && value.split('|').some((item) => item.trim().length > 0);
  }

  function humanizeAmenity(value: string): string {
    return value
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/[_-]+/g, ' ')
      .trim();
  }

  // Extract fields from data prop
  let decodedContent = $derived(asRecord(data.decodedContent) ?? {});
  let searchGroup = $derived(firstMapsGroup(decodedContent) ?? decodedContent);
  let query = $derived(typeof decodedContent.query === 'string' ? decodedContent.query : (typeof searchGroup.query === 'string' ? searchGroup.query : ''));
  let provider = $derived(typeof decodedContent.provider === 'string' ? decodedContent.provider : (typeof searchGroup.provider === 'string' ? searchGroup.provider : 'Google'));
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let warningMessages = $derived(stringArray(searchGroup.warnings));
  let filterSummary = $derived(asRecord(searchGroup.filter_summary) as MapsFilterSummary | undefined);
  let requiredAmenities = $derived(stringArray(filterSummary?.required).map(humanizeAmenity));
  let noVerifiedResults = $derived(filterSummary?.status === 'no_verified_results');
  let hasChildEmbeds = $derived(hasEmbedRefs(embedIds));

  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  let mapViewSourceRefs = $derived(embedId ? [embedId] : []);
  let mapViewHighlightRefs = $derived(initialChildEmbedId ? [initialChildEmbedId] : []);

</script>

<UnifiedEmbedFullscreen
  appId="maps"
  skillId="search"
  onClose={onClose}
  currentEmbedId={embedId}
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="maps-search-fullscreen-body">
      {#if hasChildEmbeds}
        <EmbedsMapView
          id={`${embedId || 'maps-search'}-fullscreen-map-view`}
          title={query || 'Maps search results'}
          sourceRefs={mapViewSourceRefs}
          highlightRefs={mapViewHighlightRefs}
          interactionMode="select"
        />
      {:else}
        <div class="no-results" data-testid="maps-no-results">
          <p>{$text('embeds.no_results')}</p>

          {#if noVerifiedResults || warningMessages.length > 0}
            <section class="maps-enrichment-status" data-testid="maps-enrichment-status">
              {#if noVerifiedResults}
                <h3 data-testid="maps-no-verified-results-title">{$text('embeds.maps.search.no_verified_amenities')}</h3>
                <p data-testid="maps-filter-summary">
                  {filterSummary?.verified_count ?? 0} {$text('embeds.maps.search.verified_matches')}
                  {#if typeof filterSummary?.candidate_count === 'number'}
                    {$text('embeds.maps.search.out_of_candidates').replace('{count}', String(filterSummary.candidate_count))}
                  {/if}
                </p>
                {#if requiredAmenities.length > 0}
                  <p class="required-amenities" data-testid="maps-required-amenities">
                    {$text('embeds.maps.search.required_amenities')}: {requiredAmenities.join(', ')}
                  </p>
                {/if}
              {/if}

              {#each warningMessages as warning}
                <p class="maps-warning" data-testid="maps-enrichment-warning">{warning}</p>
              {/each}
            </section>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .maps-search-fullscreen-body {
    --maps-search-fullscreen-header-height: 240px;
    --maps-search-fullscreen-body-height: calc(100% - var(--maps-search-fullscreen-header-height));

    display: flex;
    flex-direction: column;
    height: var(--maps-search-fullscreen-body-height);
    min-height: 360px;
    background: var(--color-bg-secondary);
  }

  .no-results {
    color: var(--color-font-secondary);
    font-size: 1rem;
    text-align: center;
    padding: var(--spacing-12) var(--spacing-4);
  }

  .maps-enrichment-status {
    width: min(100%, 520px);
    margin: var(--spacing-6) auto 0;
    padding: var(--spacing-5);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-5);
    background: var(--color-surface-raised, var(--color-bg-secondary));
    text-align: left;
  }

  .maps-enrichment-status h3 {
    margin: 0 0 var(--spacing-3);
    color: var(--color-font-primary);
    font-size: 0.9375rem;
    line-height: 1.3;
  }

  .maps-enrichment-status p {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: 0.875rem;
    line-height: 1.45;
  }

  .maps-enrichment-status p + p {
    margin-top: var(--spacing-3);
  }

  .required-amenities {
    text-transform: capitalize;
  }

  :global(.maps-search-fullscreen-body .embeds-map-view) {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  :global(.maps-search-fullscreen-body .map-view-body) {
    flex: 1 1 auto;
    min-height: 0;
  }

  :global(.maps-search-fullscreen-body .map-view-list),
  :global(.maps-search-fullscreen-body .map-view-map),
  :global(.maps-search-fullscreen-body .results-view-pane) {
    min-height: 0;
  }

  :global(.maps-search-fullscreen-body .map-view-list),
  :global(.maps-search-fullscreen-body .map-view-map),
  :global(.maps-search-fullscreen-body .results-view-pane),
  :global(.maps-search-fullscreen-body .results-view-calendar) {
    max-height: none;
  }

  @media (min-width: 721px) {
    :global(.maps-search-fullscreen-body .map-view-body) {
      display: grid;
      grid-template-columns: minmax(180px, 34%) minmax(0, 1fr);
    }

    :global(.maps-search-fullscreen-body .map-view-list) {
      flex-direction: column;
      height: 100%;
      overflow: auto;
      border-right: 1px solid var(--color-grey-20, #f3f3f3);
      border-bottom: 0;
    }

    :global(.maps-search-fullscreen-body .map-view-map),
    :global(.maps-search-fullscreen-body .results-view-pane),
    :global(.maps-search-fullscreen-body .results-view-calendar),
    :global(.maps-search-fullscreen-body .embed-leaflet-map) {
      height: 100%;
    }
  }

  @media (max-width: 720px) {
    .maps-search-fullscreen-body {
      --maps-search-fullscreen-header-height: 190px;

      min-height: 0;
    }

    :global(.maps-search-fullscreen-body .map-view-list) {
      flex: 0 0 auto;
      min-height: 0;
      overflow-x: auto;
      overflow-y: hidden;
    }

    :global(.maps-search-fullscreen-body .results-view-pane) {
      flex: 1 1 auto;
    }

    :global(.maps-search-fullscreen-body .map-view-map),
    :global(.maps-search-fullscreen-body .embed-leaflet-map) {
      min-height: clamp(320px, 52dvh, 520px);
    }
  }
</style>
