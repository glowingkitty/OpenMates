<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedPreview.svelte

  Child preview card for a single Urban Sports Club location or class result.
  Used by FitnessSearchEmbedFullscreen inside SearchResultsTemplate so Fitness
  search behaves like Events search: parent grid, child cards, drill-down.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
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
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }

  let { id, result, skillId, isMobile = false, resultContext = 'auto', onFullscreen }: Props = $props();

  let title = $derived(getFitnessResultTitle(result));
  let address = $derived(getFitnessResultAddress(result));
  let distance = $derived(asNumber(result.distance_km));
  let disciplines = $derived(normalizePipedList(result.disciplines));
  let imageUrl = $derived(result.image_url ? proxyImage(asText(result.image_url), MAX_WIDTH_PREVIEW_THUMBNAIL) : '');
  let classDate = $derived.by(() => {
    if (skillId !== 'search_classes' || typeof result.date !== 'string') return '';
    const value = result.date.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : '';
  });
  let classTime = $derived(skillId === 'search_classes' ? asText(result.time_range) : '');
  let classVenue = $derived(skillId === 'search_classes' ? asText(result.venue_name) : '');
  let subtitle = $derived(skillId === 'search_classes' ? undefined : address);

  async function handleStop() {
    // Child result embeds are already finished and cannot be cancelled.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="fitness"
  skillId={skillId}
  appIconName="fitness"
  skillIconName="fitness"
  status="finished"
  skillName={title}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  {resultContext}
  resultPreview={true}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={!!imageUrl && !title}
>
  {#snippet details()}
    <div class="fitness-result-preview" data-testid="fitness-result-preview"><ResultEmbedCard {title} description={subtitle} imageUrl={imageUrl} imageAlt={title} badge={classDate ? classBadge : undefined}>
      {#snippet classBadge()}<EmbedCalendarDate date={classDate} />{/snippet}
      {#snippet facts()}
        {#if skillId === 'search_classes'}<div class="fitness-preview-facts">
          {#if classTime}<span class="fitness-meta-line" data-testid="fitness-class-time" title={classTime}>{classTime}</span>{/if}
          {#if classVenue}<span class="fitness-meta-line" data-testid="fitness-class-venue" title={classVenue}>{classVenue}</span>{/if}
          <span class="fitness-meta-line">{#if distance !== undefined}{distance.toFixed(2)} km{/if}{#if result.spots_display}{distance !== undefined ? ' · ' : ''}{result.spots_display}{/if}{#if disciplines.length}{distance !== undefined || result.spots_display ? ' · ' : ''}{disciplines.slice(0, 2).join(', ')}{/if}</span>
        </div>{:else}
          {#if distance !== undefined}<span>{distance.toFixed(2)} km</span>{/if}{#if result.spots_display}<span>{result.spots_display}</span>{/if}{#if disciplines.length}<span>{disciplines.slice(0, 2).join(', ')}</span>{/if}
        {/if}
      {/snippet}
    </ResultEmbedCard></div>
  {/snippet}
</UnifiedEmbedPreview>


<style>
  .fitness-result-preview { width:100%; height:100%; }
  .fitness-preview-facts { display:flex; flex-direction:column; gap:var(--spacing-1); width:100%; min-width:0; font-size:var(--font-size-xxs); line-height:1.2; }
  .fitness-meta-line { display:block; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
