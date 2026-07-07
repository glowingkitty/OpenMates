<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedPreview.svelte

  Child preview card for a single Urban Sports Club location or class result.
  Used by FitnessSearchEmbedFullscreen inside SearchResultsTemplate so Fitness
  search behaves like Events search: parent grid, child cards, drill-down.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import {
    asNumber,
    asText,
    getFitnessResultAddress,
    getFitnessResultTitle,
    normalizePipedList,
    type FitnessResult,
    type FitnessSkillId,
  } from './fitnessEmbedData';

  interface Props {
    id: string;
    result: FitnessResult;
    skillId: FitnessSkillId;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let { id, result, skillId, isMobile = false, onFullscreen }: Props = $props();

  let imageError = $state(false);
  let title = $derived(getFitnessResultTitle(result));
  let address = $derived(getFitnessResultAddress(result));
  let distance = $derived(asNumber(result.distance_km));
  let plans = $derived(normalizePipedList(result.plans_required));
  let disciplines = $derived(normalizePipedList(result.disciplines));
  let imageUrl = $derived(result.image_url ? proxyImage(asText(result.image_url), MAX_WIDTH_PREVIEW_THUMBNAIL) : '');
  let subtitle = $derived.by(() => {
    if (skillId === 'search_classes') return [result.date, result.time_range, result.venue_name].map(asText).filter(Boolean).join(' · ');
    return address;
  });

  async function handleStop() {
    // Child result embeds are already finished and cannot be cancelled.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="fitness"
  skillId={skillId}
  skillIconName="fitness"
  status="finished"
  skillName={title}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={!!imageUrl && !title}
>
  {#snippet details({ isMobile: isMobileLayout, isLarge: isLargeLayout = false })}
    <div class="fitness-result-preview" class:mobile={isMobileLayout} class:large={isLargeLayout} data-testid="fitness-result-preview">
      <div class="fitness-result-text">
        {#if isLargeLayout}
          <div class="fitness-result-title">{title}</div>
        {/if}
        {#if subtitle}
          <div class="fitness-result-subtitle">{subtitle}</div>
        {/if}
        <div class="fitness-result-meta">
          {#if distance !== undefined}<span>{distance.toFixed(2)} km</span>{/if}
          {#if result.spots_display}<span>{result.spots_display}</span>{/if}
          {#if disciplines.length > 0}<span>{disciplines.slice(0, 2).join(', ')}</span>{/if}
          {#if plans.length > 0}<span>{plans.join(', ')}</span>{/if}
        </div>
      </div>
      {#if imageUrl && !imageError && !isMobileLayout}
        <div class="fitness-result-image">
          <img
            src={imageUrl}
            alt={title}
            loading="lazy"
            crossorigin="anonymous"
            onerror={(event) => {
              imageError = true;
              handleImageError(event.currentTarget as HTMLImageElement);
            }}
          />
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .fitness-result-preview {
    align-items: center;
    display: flex;
    gap: var(--spacing-3);
    height: 100%;
    justify-content: space-between;
    width: 100%;
  }

  .fitness-result-text {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: var(--spacing-1);
    min-width: 0;
  }

  .fitness-result-title,
  .fitness-result-subtitle,
  .fitness-result-meta span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fitness-result-title {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .fitness-result-subtitle,
  .fitness-result-meta {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .fitness-result-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
  }

  .fitness-result-image {
    border-radius: var(--radius-3);
    flex: 0 0 84px;
    height: 64px;
    overflow: hidden;
  }

  .fitness-result-image img {
    display: block;
    height: 100%;
    object-fit: cover;
    width: 100%;
  }
</style>
