<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedPreview.svelte
  
  Preview component for a single travel stay/accommodation result (child card).
  Uses UnifiedEmbedPreview as base and displays stay summary:
  - Thumbnail image (full-width)
  - Property name and star rating
  - Rating and review count
  - Amenity badges (max 3)
  - Price per night and total price
  
  Similar to TravelConnectionEmbedPreview but for accommodation results.
  This component is rendered inside TravelStaysEmbedFullscreen's grid.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { text } from '@repo/ui';
  
  /**
   * Props for travel stay embed preview
   * Data comes from the parent fullscreen component which passes
   * individual stay result fields directly.
   */
  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    /** Synthetic embed ID for this stay card */
    id: string;
    /** Property name */
    name?: string;
    /** Thumbnail URL */
    thumbnail?: string;
    /** Hotel class (1-5 stars) */
    hotelClass?: number;
    /** Overall rating (e.g., 4.3) */
    overallRating?: number;
    /** Number of reviews */
    reviews?: number;
    /** Currency code (e.g., 'EUR') */
    currency?: string;
    /** Extracted rate per night (numeric) */
    ratePerNight?: number;
    /** Extracted total rate (numeric) */
    totalRate?: number;
    /** Top amenities to display */
    amenities?: string[];
    /** Whether this is among the cheapest stays */
    isCheapest?: boolean;
    /** Eco-certified badge */
    ecoCertified?: boolean;
    /** Free cancellation badge */
    freeCancellation?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }
  
  let {
    resultContext = 'auto',
    id,
    name,
    thumbnail,
    hotelClass,
    overallRating,
    reviews,
    currency = 'EUR',
    ratePerNight,
    totalRate,
    amenities: amenitiesProp = [],
    isCheapest: _isCheapest = false,
    // ecoCertified and freeCancellation accepted but not shown in preview to keep it compact
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ecoCertified = false,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    freeCancellation = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Star rating display (e.g., "★★★★")
  let stars = $derived(
    hotelClass && hotelClass >= 1 && hotelClass <= 5
      ? '★'.repeat(hotelClass)
      : ''
  );
  
  // Formatted rating (e.g., "4.3")
  let formattedRating = $derived(
    overallRating != null ? overallRating.toFixed(1) : ''
  );
  
  // Formatted review count (e.g., "1,234")
  let formattedReviews = $derived(
    reviews != null ? reviews.toLocaleString() : ''
  );
  
  // Defensive: TOON serialization may collapse arrays into bare strings.
  let amenities = $derived(Array.isArray(amenitiesProp) ? amenitiesProp : []);
  
  // Top amenities (max 3 for preview card)
  let topAmenities = $derived(amenities.slice(0, 3));
  
  // Display name for BasicInfosBar
  let displayName = $derived(name || 'Stay');
  
  // No-op stop handler (stays don't have cancellable tasks)
  async function handleStop() {
    // Not applicable for stay result cards
  }
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="travel"
  skillId="search_stays"
  skillIconName="search"
  {status}
  skillName={displayName}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={true}
>
  {#snippet details()}
    <ResultEmbedCard title={name || 'Unknown Property'} imageUrl={thumbnail ? proxyImage(thumbnail, MAX_WIDTH_PREVIEW_THUMBNAIL) : undefined} imageAlt={name || 'Property'} description={topAmenities.join(' · ')}>
      {#snippet facts()}
        {#if ratePerNight != null}<strong>{currency} {Math.round(ratePerNight)} /{$text('embeds.night')}</strong>{/if}
        {#if formattedRating}<span>★ {formattedRating}{formattedReviews ? ` (${formattedReviews})` : ''}</span>{/if}
        {#if stars}<span>{stars}</span>{/if}
        {#if totalRate != null}<span>{currency} {Math.round(totalRate)} {$text('embeds.total')}</span>{/if}
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
