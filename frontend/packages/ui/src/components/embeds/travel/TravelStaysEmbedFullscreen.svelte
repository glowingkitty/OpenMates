<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedFullscreen.svelte
  
  Fullscreen view for Travel Search Stays skill embeds.
  Uses UnifiedEmbedFullscreen as base.
  
  Shows:
  - Header with search query, dates, and "via Google"
  - Grid of stay preview cards (TravelStayEmbedPreview) with name, price, rating, stars, thumbnail
  - Child embed overlay for individual stay detail view (TravelStayEmbedFullscreen)
  
  Stay Fullscreen Navigation (Overlay Pattern):
  - Stay results grid is ALWAYS rendered (base layer)
  - When a stay card is clicked, TravelStayEmbedFullscreen renders as OVERLAY
  - When stay fullscreen is closed, overlay is removed revealing results beneath
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
  Each stay is a separate child embed (type "stay") linked to the parent via parent_embed_id.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import TravelStayEmbedPreview from './TravelStayEmbedPreview.svelte';
  import TravelStayEmbedFullscreen from './TravelStayEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Stay result interface (transformed from decoded child embed content)
   */
  interface StayResult {
    /** Child embed ID (present for composite child embeds, absent for legacy inline results) */
    embed_id?: string;
    type?: string;
    name?: string;
    description?: string;
    property_type?: string;
    link?: string;
    property_token?: string;
    latitude?: number;
    longitude?: number;
    hotel_class?: number;
    overall_rating?: number;
    reviews?: number;
    rate_per_night?: string;
    extracted_rate_per_night?: number;
    total_rate?: string;
    extracted_total_rate?: number;
    currency?: string;
    check_in_time?: string;
    check_out_time?: string;
    amenities?: string[];
    images?: Array<{ thumbnail?: string; original_image?: string }>;
    thumbnail?: string;
    nearby_places?: Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }>;
    eco_certified?: boolean;
    free_cancellation?: boolean;
    hash?: string;
  }
  
  /**
   * Props for travel stays embed fullscreen
   */
  interface Props {
    /** Search query */
    query?: string;
    /** Search provider */
    provider?: string;
    /** Pipe-separated embed IDs or array of embed IDs for child stay embeds */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Legacy: results array (used if embedIds not provided - backwards compat) */
    results?: unknown[];
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }
  
  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Currently selected stay for fullscreen detail view (overlay)
  let selectedStay = $state<StayResult | null>(null);
  
  // Local reactive state
  let localQuery = $state<string>(queryProp || '');
  let localProvider = $state<string>(providerProp || 'Google');
  let localEmbedIds = $state<string | string[] | undefined>(embedIds);
  let localResults = $state<unknown[]>(resultsProp || []);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>(statusProp || 'finished');
  let localErrorMessage = $state<string>(errorMessageProp || '');
  
  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localEmbedIds = embedIds;
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });
  
  // Derived state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(localEmbedIds);
  let legacyResults = $derived(localResults);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));
  
  // Skill name from translations
  let skillName = $derived($text('app_skills.travel.search_stays'));
  
  // "via {provider}" text
  let viaProvider = $derived(
    `${$text('embeds.via')} ${provider}`
  );
  
  // =========================================================================
  // Child Embed Transformer
  // =========================================================================
  
  /**
   * Reconstruct an array from TOON-flattened keys.
   * TOON flattening turns amenities: ["pool","wifi"] → amenities_0: "pool", amenities_1: "wifi"
   */
  function reconstructStringArray(content: Record<string, unknown>, prefix: string): string[] {
    // If already an array, return directly
    if (Array.isArray(content[prefix])) {
      return content[prefix] as string[];
    }
    const arr: string[] = [];
    for (let i = 0; i < 50; i++) {
      const val = content[`${prefix}_${i}`];
      if (typeof val === 'string') {
        arr.push(val);
      } else {
        break;
      }
    }
    return arr;
  }
  
  /**
   * Reconstruct images array from TOON-flattened keys.
   * TOON: images_0_thumbnail, images_0_original_image, images_1_thumbnail, ...
   */
  function reconstructImages(content: Record<string, unknown>): Array<{ thumbnail?: string; original_image?: string }> {
    if (Array.isArray(content.images)) {
      return (content.images as Record<string, unknown>[]).map(img => ({
        thumbnail: img.thumbnail as string | undefined,
        original_image: img.original_image as string | undefined,
      }));
    }
    const images: Array<{ thumbnail?: string; original_image?: string }> = [];
    for (let i = 0; i < 20; i++) {
      const thumb = content[`images_${i}_thumbnail`];
      const orig = content[`images_${i}_original_image`];
      if (thumb || orig) {
        images.push({
          thumbnail: thumb as string | undefined,
          original_image: orig as string | undefined,
        });
      } else {
        break;
      }
    }
    return images;
  }
  
  /**
   * Reconstruct nearby_places array from TOON-flattened keys.
   * TOON: nearby_places_0_name, nearby_places_0_transportations_0_type, ...
   */
  function reconstructNearbyPlaces(content: Record<string, unknown>): Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }> {
    if (Array.isArray(content.nearby_places)) {
      return (content.nearby_places as Record<string, unknown>[]).map(place => ({
        name: place.name as string | undefined,
        transportations: Array.isArray(place.transportations) 
          ? (place.transportations as Record<string, unknown>[]).map(t => ({
              type: t.type as string | undefined,
              duration: t.duration as string | undefined,
            }))
          : undefined,
      }));
    }
    const places: Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }> = [];
    for (let i = 0; i < 10; i++) {
      const name = content[`nearby_places_${i}_name`];
      if (name === undefined && content[`nearby_places_${i}_transportations_0_type`] === undefined) {
        break;
      }
      // Reconstruct transportations for this place
      const transports: Array<{ type?: string; duration?: string }> = [];
      for (let j = 0; j < 10; j++) {
        const tType = content[`nearby_places_${i}_transportations_${j}_type`];
        const tDuration = content[`nearby_places_${i}_transportations_${j}_duration`];
        if (tType || tDuration) {
          transports.push({
            type: tType as string | undefined,
            duration: tDuration as string | undefined,
          });
        } else {
          break;
        }
      }
      places.push({
        name: name as string | undefined,
        transportations: transports.length > 0 ? transports : undefined,
      });
    }
    return places;
  }
  
  /**
   * Transform raw embed content to StayResult format.
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer.
   * 
   * TOON encoding flattens nested objects (amenities, images, nearby_places).
   * We reconstruct them from the flattened keys.
   */
  function transformToStayResult(embedId: string, content: Record<string, unknown>): StayResult {
    return {
      embed_id: embedId,
      type: (content.type as string) || 'stay',
      name: content.name as string | undefined,
      description: content.description as string | undefined,
      property_type: content.property_type as string | undefined,
      link: content.link as string | undefined,
      property_token: content.property_token as string | undefined,
      latitude: content.latitude as number | undefined,
      longitude: content.longitude as number | undefined,
      hotel_class: content.hotel_class as number | undefined,
      overall_rating: content.overall_rating as number | undefined,
      reviews: content.reviews as number | undefined,
      rate_per_night: content.rate_per_night as string | undefined,
      extracted_rate_per_night: content.extracted_rate_per_night as number | undefined,
      total_rate: content.total_rate as string | undefined,
      extracted_total_rate: content.extracted_total_rate as number | undefined,
      currency: (content.currency as string) || 'EUR',
      check_in_time: content.check_in_time as string | undefined,
      check_out_time: content.check_out_time as string | undefined,
      amenities: reconstructStringArray(content, 'amenities'),
      images: reconstructImages(content),
      thumbnail: content.thumbnail as string | undefined,
      nearby_places: reconstructNearbyPlaces(content),
      eco_certified: content.eco_certified === true || content.eco_certified === 'true',
      free_cancellation: content.free_cancellation === true || content.free_cancellation === 'true',
      hash: content.hash as string | undefined,
    };
  }
  
  // =========================================================================
  // Stay Results Extraction
  // =========================================================================
  
  /**
   * Get stay results from context.
   * Prefers child embeds (ctx.children) over legacy results (ctx.legacyResults).
   */
  function getStayResults(ctx: ChildEmbedContext): StayResult[] {
    // Prefer child embeds (new pattern: each stay is a separate embed)
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as StayResult[];
    }
    // Fallback: legacy results (inline data, backwards compatibility)
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return flattenStayResults(ctx.legacyResults);
    }
    return [];
  }
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}] for multi-request)
   * Only used for legacy/backwards-compat path.
   */
  function flattenStayResults(rawResults: unknown[]): StayResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: StayResult[] = [];
      for (const entry of rawResults as Array<{ id?: string; results?: StayResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    
    return rawResults as StayResult[];
  }
  
  /**
   * Calculate the cheapest 20% price threshold for highlighting
   */
  function getCheapestThreshold(results: StayResult[]): number {
    const prices = results
      .filter(r => r.extracted_rate_per_night != null && r.extracted_rate_per_night > 0)
      .map(r => r.extracted_rate_per_night!)
      .sort((a, b) => a - b);
    if (prices.length === 0) return 0;
    // Bottom 20% index (at least 1 result)
    const idx = Math.max(0, Math.ceil(prices.length * 0.2) - 1);
    return prices[idx];
  }
  
  /**
   * Get first thumbnail image URL for a property
   */
  function getThumbnail(stay: StayResult): string | undefined {
    if (stay.thumbnail) return stay.thumbnail;
    if (stay.images && stay.images.length > 0) {
      return stay.images[0].thumbnail || stay.images[0].original_image;
    }
    return undefined;
  }
  
  // =========================================================================
  // Event Handlers
  // =========================================================================
  
  /**
   * Handle stay card click - opens detail fullscreen as overlay
   */
  function handleStayFullscreen(stay: StayResult) {
    console.debug('[TravelStaysEmbedFullscreen] Opening stay fullscreen:', {
      embed_id: stay.embed_id,
      name: stay.name,
      rating: stay.overall_rating,
      price: stay.extracted_rate_per_night,
    });
    selectedStay = stay;
  }
  
  /**
   * Handle closing the stay detail fullscreen overlay
   */
  function handleStayFullscreenClose() {
    selectedStay = null;
  }
  
  /**
   * Handle closing the entire search fullscreen.
   * If a stay detail overlay is open, close it first; otherwise close the parent.
   */
  function handleMainClose() {
    if (selectedStay) {
      selectedStay = null;
    } else {
      onClose();
    }
  }
  
  /**
   * Handle embed data updates during streaming
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    // Update embed IDs when parent embed is updated with child references
    if (content.embed_ids) localEmbedIds = content.embed_ids as string | string[];
    // Legacy: inline results (backwards compat)
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<!-- Stay results view - ALWAYS rendered (base layer) -->
<UnifiedEmbedFullscreen
  appId="travel"
  skillId="search_stays"
  title=""
  onClose={handleMainClose}
  skillIconName="search"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToStayResult}
  legacyResults={legacyResults}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const stayResults = getStayResults(ctx)}
    {@const cheapestThreshold = getCheapestThreshold(stayResults)}
    
    <!-- Header with search query and provider -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    <!-- Error state -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">{$text('embeds.search_failed')}</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else}
      {#if stayResults.length === 0}
        {#if ctx.isLoadingChildren}
          <div class="loading-state">
            <p>{$text('embeds.loading')}</p>
          </div>
        {:else}
          <div class="no-results">
            <p>{$text('embeds.no_stays_found')}</p>
          </div>
        {/if}
      {:else}
        <!-- Stay property cards grid (using TravelStayEmbedPreview) -->
        <div class="stays-grid">
          {#each stayResults as stay, index}
            {@const isCheapest = cheapestThreshold > 0 && stay.extracted_rate_per_night != null && stay.extracted_rate_per_night <= cheapestThreshold}
            
            <TravelStayEmbedPreview
              id={stay.embed_id || stay.hash || `stay-${index}`}
              name={stay.name}
              thumbnail={getThumbnail(stay)}
              hotelClass={stay.hotel_class}
              overallRating={stay.overall_rating}
              reviews={stay.reviews}
              currency={stay.currency}
              ratePerNight={stay.extracted_rate_per_night}
              totalRate={stay.extracted_total_rate}
              amenities={stay.amenities?.slice(0, 3)}
              {isCheapest}
              ecoCertified={stay.eco_certified}
              freeCancellation={stay.free_cancellation}
              status="finished"
              isMobile={false}
              onFullscreen={() => handleStayFullscreen(stay)}
            />
          {/each}
        </div>
      {/if}
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Stay detail fullscreen overlay -->
{#if selectedStay}
  <ChildEmbedOverlay>
    <TravelStayEmbedFullscreen
      stay={selectedStay}
      onClose={handleStayFullscreenClose}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  /* ===========================================
     Fullscreen Header
     =========================================== */
  
  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 40px;
    padding: 0 16px;
    text-align: center;
  }
  
  .search-query {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .search-provider {
    font-size: 16px;
    color: var(--color-font-secondary);
    margin-top: 8px;
  }
  
  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 24px;
    }
    
    .search-query {
      font-size: 20px;
    }
    
    .search-provider {
      font-size: 14px;
    }
  }
  
  /* ===========================================
     Loading, No Results and Error States
     =========================================== */
  
  .loading-state,
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }
  
  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }
  
  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }
  
  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }
  
  /* ===========================================
     Stays Grid
     =========================================== */
  
  .stays-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
  
  @container fullscreen (max-width: 500px) {
    .stays-grid {
      grid-template-columns: 1fr;
    }
  }
  
  /* Allow stay preview cards to fill the grid cell */
  .stays-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>
