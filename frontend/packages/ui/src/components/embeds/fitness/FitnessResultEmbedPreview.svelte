<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedPreview.svelte

  Child preview card for a single Urban Sports Club location or class result.
  Used by FitnessSearchEmbedFullscreen inside SearchResultsTemplate so Fitness
  search behaves like Events search: parent grid, child cards, drill-down.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
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
    <div class="fitness-result-preview" data-testid="fitness-result-preview"><ResultEmbedCard {title} description={subtitle} imageUrl={imageUrl} imageAlt={title}>
      {#snippet facts()}{#if distance !== undefined}<span>{distance.toFixed(2)} km</span>{/if}{#if result.spots_display}<span>{result.spots_display}</span>{/if}{#if disciplines.length}<span>{disciplines.slice(0, 2).join(', ')}</span>{/if}{/snippet}
    </ResultEmbedCard></div>
  {/snippet}
</UnifiedEmbedPreview>


<style>.fitness-result-preview { width:100%; height:100%; }</style>
