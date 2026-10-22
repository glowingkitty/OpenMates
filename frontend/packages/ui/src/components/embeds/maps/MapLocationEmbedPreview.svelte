<!--
  frontend/packages/ui/src/components/embeds/maps/MapLocationEmbedPreview.svelte

  Preview card for a single maps-place result shown inside MapsSearchEmbedFullscreen's
  result list. Based on UnifiedEmbedPreview.

  Displays:
  - Place name (bold)
  - Rating with star and review count
  - Formatted address (muted)
  - Category/type badge if available

  This component is rendered inside MapsSearchEmbedFullscreen's left-panel list.
  Clicking it opens MapLocationEmbedFullscreen (via onFullscreen callback).

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  /**
   * Props for a single place result preview card.
   * Data comes from the parent search fullscreen which passes
   * individual place result fields directly.
   */
  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    /** Synthetic embed ID for this place card */
    id: string;
    /** Place display name */
    displayName?: string;
    /** Formatted address */
    formattedAddress?: string;
    /** Rating (0–5) */
    rating?: number;
    /** Number of user ratings */
    userRatingCount?: number;
    /** Place category/type (e.g. "Coffee Shop") */
    placeType?: string;
    dataSource?: string;
    distanceMeters?: number;
    /** Place photo URL (Google Places photo/media URL) */
    imageUrl?: string;
    /** Whether this is the currently selected/highlighted place */
    isSelected?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler to open fullscreen location details */
    onFullscreen: () => void;
  }

  let {
    resultContext = 'auto',
    id,
    displayName,
    formattedAddress,
    rating,
    userRatingCount,
    placeType,
    dataSource,
    distanceMeters,
    imageUrl,
    isSelected = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let skillName = $derived($text('common.location'));

  /** Format rating to 1 decimal, capped to avoid floating point noise */
  let ratingText = $derived(
    rating != null ? rating.toFixed(1) : null
  );

  let proxiedImageUrl = $derived(
    imageUrl ? proxyImage(imageUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : ''
  );
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="maps"
  skillId="location"
  skillIconName="pin"
  {status}
  {skillName}
  {isMobile}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <div class="place-card" data-testid="maps-place-card" class:selected={isSelected} data-selected={isSelected}>
      <ResultEmbedCard title={displayName || $text('common.location')} description={formattedAddress} imageUrl={proxiedImageUrl || undefined} imageAlt={displayName || $text('common.location')} sourceLabel={placeType}>
        {#snippet facts()}
          {#if ratingText != null}<span>★ {ratingText}{userRatingCount != null ? ` (${userRatingCount.toLocaleString()})` : ''}</span>{/if}
          {#if distanceMeters != null && Number.isFinite(distanceMeters)}<span data-testid="maps-place-distance">{distanceMeters < 1000 ? `${Math.round(distanceMeters)} m` : `${(distanceMeters / 1000).toFixed(1)} km`}</span>{/if}
          {#if dataSource}<span data-testid="maps-place-source">{dataSource}</span>{/if}
        {/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>
<style>
  .place-card { width: 100%; height: 100%; }
  .place-card.selected { outline: 2px solid var(--color-primary); outline-offset: -2px; border-radius: var(--radius-6); }
  .place-card.selected :global(h3) { color: var(--color-primary); }
</style>
