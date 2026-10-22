<!--
  frontend/packages/ui/src/components/embeds/home/HomeSearchEmbedFullscreen.svelte

  Fullscreen view for Home Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query (city) and "via Multi" subtitle
  - Listing cards in a responsive grid
  - Overlay drill-down into HomeListingEmbedFullscreen

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { homeListingContent, homeNumber, homeImages, homeMatchesFilters, homeApproximate } from './homeListingData';
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import HomeListingEmbedPreview from './HomeListingEmbedPreview.svelte';
  import HomeListingEmbedFullscreen from './HomeListingEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { getLucideIcon } from '../../../utils/categoryUtils';
  import { text } from '@repo/ui';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  const PriceFilterIcon = getLucideIcon('banknote');
  const RoomFilterIcon = getLucideIcon('bed-double');
  const AreaFilterIcon = getLucideIcon('ruler');
  const TypeFilterIcon = getLucideIcon('layers');


  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  /**
   * Home listing result interface (transformed from child embeds).
   * Contains all fields needed for both preview cards and fullscreen view.
   */
  interface HomeListingResult extends Record<string, unknown> {
    embed_id: string;
    title?: string;
    price_label?: string;
    size_sqm?: number;
    rooms?: number;
    address?: string;
    image_url?: string;
    url?: string;
    provider?: string;
    listing_type?: string;
    available_from?: string;
    deposit?: number;
    furnished?: boolean;
    /** Geocoded coordinates — forwarded to HomeListingEmbedFullscreen so
     *  each child listing can render its own Leaflet map. Read directly
     *  as flat fields (dc.latitude / dc.longitude). */
    latitude?: number;
    longitude?: number;
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

  let maxPrice = $state<number | undefined>();
  let priceBasis = $state<'advertised' | 'warm' | 'cold'>('advertised');
  let minRooms = $state<number | undefined>();
  let minSize = $state<number | undefined>();
  let requiredAmenity = $state('');
  const amenityOptions = ['balcony', 'terrace', 'garden', 'elevator', 'furnished', 'parking', 'pets_allowed'];
  function matchesHomeFilters(result: HomeListingResult): boolean {
    return homeMatchesFilters(result, { maxPrice, priceBasis, minRooms, minSize, requiredAmenity });
  }
  function resetHomeFilters() {
    maxPrice = undefined; priceBasis = 'advertised'; minRooms = undefined; minSize = undefined; requiredAmenity = '';
  }

  // Extract fields from data prop
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  // Local reactive state for streaming updates
  let localQuery = $state('');
  let localProvider = $state('Multi');
  let localProviders = $state<string[]>([]);
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');
  let localWarnings = $state<string[]>([]);
  function warningMessages(value: unknown): string[] {
    if (typeof value === 'string') {
      try { return warningMessages(JSON.parse(value)); } catch { return value.trim() ? [value.trim()] : []; }
    }
    return Array.isArray(value) ? value.flatMap(item => typeof item === 'string' && item.trim() ? [item.trim()] : []) : [];
  }

  $effect(() => {
    localWarnings = warningMessages(data.decodedContent?.warnings);
    localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
    localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Multi';
    localProviders = Array.isArray(data.decodedContent?.providers) ? data.decodedContent.providers as string[] : [];
    localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
    localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error as string : '';
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let providers = $derived(localProviders);
  let legacyResults = $derived(extractSearchResultsFromContent(data.decodedContent));

  // "via {provider}" subtitle — use providers list when available for multi-source display
  let viaProvider = $derived.by(() => {
    const via = $text('embeds.via');
    if (providers.length > 0) {
      if (providers.length <= 2) {
        return `${via} ${providers.join(', ')}`;
      }
      return `${via} ${providers[0]}, ${providers[1]} +${providers.length - 2}`;
    }
    if (provider && provider !== 'Multi') {
      return `${via} ${provider}`;
    }
    return '';
  });

  /**
   * Transform raw embed content to HomeListingResult format.
   */
  function transformToHomeResult(
    embedId: string,
    content: Record<string, unknown>
  ): HomeListingResult {
    content = homeListingContent(content);
    return {
      ...content,
      embed_id: embedId,
      image_url: homeImages(content.image_urls, content.image_url)[0],
      size_sqm: homeNumber(content.size_sqm),
      rooms: homeNumber(content.rooms),
      latitude: homeNumber(content.latitude),
      longitude: homeNumber(content.longitude)

    };
  }

  /**
   * Transform legacy results for backwards compatibility.
   */
  function transformLegacyResults(results: unknown[]): HomeListingResult[] {
    return (results as Array<Record<string, unknown>>).map((result, index) => transformToHomeResult(`legacy-${index}`, result));
  }

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }) {
    if (!data.decodedContent) return;
    const s = data.status;
    if (s === 'processing' || s === 'finished' || s === 'error' || s === 'cancelled')
      localStatus = s;
    const c = data.decodedContent;
    if (typeof c.query === 'string') localQuery = c.query;
    if (typeof c.provider === 'string') localProvider = c.provider;
    if (Array.isArray(c.providers)) localProviders = c.providers as string[];
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
    if (typeof c.error === 'string') localErrorMessage = c.error;
    if ('warnings' in c) localWarnings = warningMessages(c.warnings);
  }
</script>

{#snippet homeFilterNotices()}
  {#if localWarnings.length}
    <div class="home-search-notices" role="status" aria-live="polite" data-testid="home-search-warnings">
      {#each localWarnings as warning}<p>{warning}</p>{/each}
    </div>
  {/if}
{/snippet}

{#snippet homeFilterControls()}
  <div class="home-filters" data-testid="home-filters">
    <div class="home-filter-fields">
      <label><span class="filter-section-title"><PriceFilterIcon size={23} />{$text('home_listing.max_price')}</span><input type="number" min="0" step="any" bind:value={maxPrice} data-testid="home-filter-max-price" /></label>
      <label><span class="filter-section-title"><TypeFilterIcon size={23} />{$text('home_listing.price_type')}</span><select bind:value={priceBasis} data-testid="home-filter-price-basis">
        <option value="advertised">{$text('home_listing.advertised_price')}</option>
        <option value="warm">{$text('home_listing.warm_rent_eur')}</option>
        <option value="cold">{$text('home_listing.cold_rent_eur')}</option>
      </select></label>
      <label><span class="filter-section-title"><RoomFilterIcon size={23} />{$text('home_listing.min_rooms')}</span><input type="number" min="0" step="0.5" bind:value={minRooms} data-testid="home-filter-min-rooms" /></label>
      <label><span class="filter-section-title"><AreaFilterIcon size={23} />{$text('home_listing.min_size')}</span><input type="number" min="0" step="any" bind:value={minSize} data-testid="home-filter-min-size" /></label>
      <label><span class="filter-section-title"><TypeFilterIcon size={23} />{$text('home_listing.required_amenity')}</span><select bind:value={requiredAmenity} data-testid="home-filter-amenity">
        <option value="">{$text('home_listing.any_amenity')}</option>
        {#each amenityOptions as amenity}<option value={amenity}>{$text(`home_listing.${amenity}`)}</option>{/each}
      </select></label>
    </div>
    <p>{$text('home_listing.filter_unknown_warning')}</p>
  </div>
{/snippet}

<SearchResultsTemplate
  filters={{ controls: homeFilterControls, notices: homeFilterNotices, reset: resetHomeFilters, matches: matchesHomeFilters }}
  appId="home"
  skillId="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToHomeResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <HomeListingEmbedPreview
      embed_id={result.embed_id}
      title={result.title}
      price_label={result.price_label}
      size_sqm={result.size_sqm}
      rooms={result.rooms}
      address={result.address}
      image_url={result.image_url}
      provider={result.provider}
      listing_type={result.listing_type}
      available_from={result.available_from}
      location_precision={result.location_precision as string | undefined}
      location_approximate={homeApproximate(result)}
      {onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <HomeListingEmbedFullscreen
      data={{ decodedContent: nav.result }}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  .home-search-notices { display: grid; gap: var(--spacing-3); padding: var(--spacing-4); margin-bottom: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); background: var(--color-grey-10); color: var(--color-font-primary); }
  .home-search-notices p { margin: 0; font-size: .875rem; line-height: 1.6; overflow-wrap: anywhere; }
  /* Same stacked sections, icon headings and type hierarchy as the map/calendar filter panel. */
  .home-filters { min-width: 0; color: var(--color-font-primary); }
  .home-filter-fields { display: flex; flex-direction: column; gap: 25px; }
  .home-filters label { display: flex; flex-direction: column; flex-shrink: 0; gap: 12px; min-width: 0; }
  .filter-section-title { display: flex; align-items: center; gap: 20px; border-bottom: 3px solid var(--color-primary-start); padding: 0 8px 7px; color: var(--color-font-primary); font-size: var(--font-size-p); font-weight: 650; }
  .filter-section-title :global(svg) { color: var(--color-primary-start); flex-shrink: 0; }
  .home-filters input, .home-filters select { box-sizing: border-box; width: 100%; min-width: 0; max-width: none; min-height: 42px; margin: 0; padding: var(--spacing-3) var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-0); color: var(--color-font-primary); box-shadow: none; font: inherit; font-size: var(--font-size-small); font-weight: 550; }
  .home-filters input:focus-visible, .home-filters select:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .home-filters p { margin: 20px 0 0; font-size: var(--font-size-small); line-height: 1.5; color: var(--color-font-tertiary); }
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="home"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }
</style>
