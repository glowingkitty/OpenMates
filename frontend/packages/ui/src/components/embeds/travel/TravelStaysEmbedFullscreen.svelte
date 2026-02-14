<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedFullscreen.svelte
  
  Fullscreen view for Travel Search Stays skill embeds.
  Uses UnifiedEmbedFullscreen as base.
  
  Shows:
  - Header with search query, dates, and "via Google"
  - Grid of property cards with name, price, rating, stars, thumbnail, amenities
  - No child embed overlay needed (stays are stored directly in parent embed)
  
  This is a non-composite skill: the embed data contains the full results
  array directly (no child embeds).
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Stay result interface (from decoded embed content)
   */
  interface StayResult {
    type?: string;
    name?: string;
    description?: string;
    property_type?: string;
    link?: string;
    property_token?: string;
    gps_coordinates?: { latitude: number; longitude: number };
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
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Results array (non-composite: data embedded directly) */
    results?: StayResult[];
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
  
  // Local reactive state
  let localQuery = $state<string>(queryProp || '');
  let localProvider = $state<string>(providerProp || 'Google');
  let localResults = $state<unknown[]>(resultsProp || []);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>(statusProp || 'finished');
  let localErrorMessage = $state<string>(errorMessageProp || '');
  
  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });
  
  // Derived state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
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
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}] for multi-request)
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
   * Get stay results from context (legacy results flow for non-composite embeds)
   */
  function getStayResults(ctx: ChildEmbedContext): StayResult[] {
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return flattenStayResults(ctx.legacyResults);
    }
    return [];
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
   * Render star rating as "★★★★" text
   */
  function renderStars(hotelClass?: number): string {
    if (!hotelClass || hotelClass < 1 || hotelClass > 5) return '';
    return '★'.repeat(hotelClass);
  }
  
  /**
   * Format rating (e.g., 4.3 -> "4.3")
   */
  function formatRating(rating?: number): string {
    if (rating == null) return '';
    return rating.toFixed(1);
  }
  
  /**
   * Format review count (e.g., 1234 -> "1,234")
   */
  function formatReviews(reviews?: number): string {
    if (reviews == null) return '';
    return reviews.toLocaleString();
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
  
  /**
   * Top amenities to display (max 3 badges)
   */
  function getTopAmenities(stay: StayResult): string[] {
    if (!stay.amenities || stay.amenities.length === 0) return [];
    return stay.amenities.slice(0, 3);
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
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<!-- Stay results view -->
<UnifiedEmbedFullscreen
  appId="travel"
  skillId="search_stays"
  title=""
  onClose={onClose}
  skillIconName="search"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
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
        <!-- Stay property cards grid -->
        <div class="stays-grid">
          {#each stayResults as stay}
            {@const thumb = getThumbnail(stay)}
            {@const isCheapest = cheapestThreshold > 0 && stay.extracted_rate_per_night != null && stay.extracted_rate_per_night <= cheapestThreshold}
            {@const amenities = getTopAmenities(stay)}
            
            <div class="stay-card" class:cheapest={isCheapest}>
              <!-- Thumbnail -->
              {#if thumb}
                <div class="stay-thumbnail">
                  <img src={thumb} alt={stay.name || 'Property'} loading="lazy" />
                </div>
              {:else}
                <div class="stay-thumbnail placeholder">
                  <span class="placeholder-icon">🏨</span>
                </div>
              {/if}
              
              <!-- Card body -->
              <div class="stay-body">
                <!-- Name and star rating -->
                <div class="stay-header">
                  <div class="stay-name">{stay.name || 'Unknown'}</div>
                  {#if stay.hotel_class}
                    <div class="stay-stars">{renderStars(stay.hotel_class)}</div>
                  {/if}
                </div>
                
                <!-- Rating and reviews -->
                {#if stay.overall_rating}
                  <div class="stay-rating">
                    <span class="rating-value">{formatRating(stay.overall_rating)}</span>
                    {#if stay.reviews}
                      <span class="rating-reviews">({formatReviews(stay.reviews)})</span>
                    {/if}
                  </div>
                {/if}
                
                <!-- Amenities badges -->
                {#if amenities.length > 0}
                  <div class="stay-amenities">
                    {#each amenities as amenity}
                      <span class="amenity-badge">{amenity}</span>
                    {/each}
                  </div>
                {/if}
                
                <!-- Special badges (eco, free cancellation) -->
                {#if stay.eco_certified || stay.free_cancellation}
                  <div class="stay-badges">
                    {#if stay.free_cancellation}
                      <span class="badge badge-cancellation">{$text('embeds.free_cancellation')}</span>
                    {/if}
                    {#if stay.eco_certified}
                      <span class="badge badge-eco">{$text('embeds.eco_certified')}</span>
                    {/if}
                  </div>
                {/if}
                
                <!-- Price -->
                <div class="stay-price">
                  {#if stay.rate_per_night || stay.extracted_rate_per_night}
                    <span class="price-amount">
                      {stay.currency || 'EUR'} {Math.round(stay.extracted_rate_per_night || 0)}
                    </span>
                    <span class="price-per-night">/{$text('embeds.night')}</span>
                  {/if}
                  {#if stay.total_rate || stay.extracted_total_rate}
                    <span class="price-total">
                      {stay.currency || 'EUR'} {Math.round(stay.extracted_total_rate || 0)} {$text('embeds.total')}
                    </span>
                  {/if}
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

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
  
  /* ===========================================
     Stay Card
     =========================================== */
  
  .stay-card {
    border-radius: 16px;
    overflow: hidden;
    background: var(--color-card-bg, var(--color-grey-10));
    border: 1px solid var(--color-grey-20);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  
  .stay-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }
  
  .stay-card.cheapest {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 1px var(--color-primary);
  }
  
  /* Thumbnail */
  .stay-thumbnail {
    width: 100%;
    height: 160px;
    overflow: hidden;
    background: var(--color-grey-15);
  }
  
  .stay-thumbnail img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  
  .stay-thumbnail.placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .placeholder-icon {
    font-size: 32px;
    opacity: 0.4;
  }
  
  /* Card body */
  .stay-body {
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  
  /* Header (name + stars) */
  .stay-header {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .stay-name {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .stay-stars {
    font-size: 12px;
    color: #f5a623;
    letter-spacing: 1px;
  }
  
  /* Rating */
  .stay-rating {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
  }
  
  .rating-value {
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .rating-reviews {
    color: var(--color-font-secondary);
  }
  
  /* Amenities */
  .stay-amenities {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  
  .amenity-badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--color-grey-15);
    color: var(--color-font-secondary);
    white-space: nowrap;
  }
  
  /* Special badges */
  .stay-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  
  .badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    white-space: nowrap;
  }
  
  .badge-cancellation {
    background: rgba(76, 175, 80, 0.12);
    color: #4caf50;
  }
  
  .badge-eco {
    background: rgba(33, 150, 243, 0.12);
    color: #2196f3;
  }
  
  /* Price */
  .stay-price {
    display: flex;
    align-items: baseline;
    gap: 4px;
    flex-wrap: wrap;
    margin-top: 2px;
  }
  
  .price-amount {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-font-primary);
  }
  
  .price-per-night {
    font-size: 13px;
    color: var(--color-font-secondary);
  }
  
  .price-total {
    font-size: 12px;
    color: var(--color-font-secondary);
    margin-left: auto;
  }
</style>
