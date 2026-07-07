<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedFullscreen.svelte

  Fullscreen renderer for Fitness Urban Sports search embeds. Uses the unified
  SearchResultsTemplate parent/child layout so Fitness matches Events search:
  parent result grid, child preview cards, and drill-down fullscreen details.
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import FitnessResultEmbedPreview from './FitnessResultEmbedPreview.svelte';
  import FitnessResultEmbedFullscreen from './FitnessResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    asText,
    normalizeFitnessSearchContent,
    normalizeFitnessSkillId,
    type FitnessResult,
    type FitnessSkillId,
    type FitnessStatus,
  } from './fitnessEmbedData';

  interface Props {
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

  interface FitnessChildResult extends FitnessResult {
    embed_id: string;
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

  let updatedContent = $state<Record<string, unknown> | null>(null);
  let content = $derived((updatedContent ?? data.decodedContent ?? data.embedData ?? {}) as Record<string, unknown>);
  let fallbackSkillId = $derived(normalizeFitnessSkillId(content.skill_id || data.embedData?.skill_id, 'search_classes'));
  let normalized = $derived(normalizeFitnessSearchContent(content, fallbackSkillId));
  let skillId: FitnessSkillId = $derived(normalized.skillId);
  let status: FitnessStatus = $derived(normalized.status);
  let embedIds = $derived(normalized.embedIds ?? data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let title = $derived(normalized.query || (skillId === 'search_locations' ? 'Fitness locations' : 'Fitness classes'));
  let headerSubtitle = $derived.by(() => {
    const summary = normalized.summary || `${normalized.resultCount} ${skillId === 'search_locations' ? 'locations' : 'classes'}`;
    return [normalized.provider, summary].filter(Boolean).join(' · ');
  });

  function transformToFitnessResult(childEmbedId: string, childContent: Record<string, unknown>): FitnessChildResult {
    return {
      ...childContent,
      embed_id: childEmbedId,
      skill_id: childContent.skill_id || skillId,
    } as FitnessChildResult;
  }

  function transformLegacyResults(results: unknown[]): FitnessChildResult[] {
    return (results as FitnessResult[]).map((result, index) => ({
      ...result,
      embed_id: asText(result.embed_id) || `legacy-fitness-${index}`,
      skill_id: result.skill_id || skillId,
    } as FitnessChildResult));
  }

  function handleEmbedDataUpdated(update: { status: string; decodedContent: Record<string, unknown> }) {
    updatedContent = {
      ...update.decodedContent,
      status: update.status,
    };
  }
</script>

<SearchResultsTemplate
  appId="fitness"
  {skillId}
  embedHeaderTitle={title}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="fitness"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToFitnessResult}
  legacyResults={normalized.results}
  legacyResultTransformer={transformLegacyResults}
  {status}
  query={normalized.query}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  minCardWidth="260px"
>
  {#snippet resultCard({ result, onSelect })}
    <FitnessResultEmbedPreview
      id={result.embed_id}
      {result}
      {skillId}
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <FitnessResultEmbedFullscreen
      data={{ decodedContent: nav.result }}
      embedId={nav.result.embed_id}
      onClose={nav.onClose}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
