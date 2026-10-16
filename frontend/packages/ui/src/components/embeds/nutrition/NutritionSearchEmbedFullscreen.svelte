<!--
  frontend/packages/ui/src/components/embeds/nutrition/NutritionSearchEmbedFullscreen.svelte

  Fullscreen view for the Nutrition Search Recipes skill embed.
  Uses SearchResultsTemplate for unified search grid + child fullscreen overlay.
  Renders NutritionRecipeEmbedPreview cards and drills into NutritionRecipeEmbedFullscreen.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import NutritionRecipeEmbedPreview from './NutritionRecipeEmbedPreview.svelte';
  import NutritionRecipeEmbedFullscreen from './NutritionRecipeEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';
  import { parseRecipeResult, type RecipeResult } from './recipeNutrition';

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
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
    onShowChat
  }: Props = $props();

  // Extract fields from data prop
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  let localQuery = $state('');
  let localProvider = $state('Edamam');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let storeResolved = $state(false);
  let localErrorMessage = $state('');

  $effect(() => {
    if (!storeResolved) {
      localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
      localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Edamam';
      localResults = extractSearchResultsFromContent(data.decodedContent);
      localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
      localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error as string : '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let legacyResults = $derived(localResults);

  function transformLegacyResults(results: unknown[]): RecipeResult[] {
    const transformed: RecipeResult[] = [];

    for (let i = 0; i < results.length; i++) {
      const item = results[i] as Record<string, unknown>;
      if (!item || typeof item !== 'object') continue;

      const groupedResults = item.results;
      if (Array.isArray(groupedResults)) {
        for (let j = 0; j < groupedResults.length; j++) {
          const groupedItem = groupedResults[j] as Record<string, unknown>;
          if (!groupedItem || typeof groupedItem !== 'object') continue;
          transformed.push(parseRecipeResult(`legacy-${i}-${j}`, groupedItem));
        }
        continue;
      }

      transformed.push(parseRecipeResult(`legacy-${i}`, item));
    }

    return transformed;
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;

    if (
      data.status === 'processing' ||
      data.status === 'finished' ||
      data.status === 'error' ||
      data.status === 'cancelled'
    ) {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results;
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  let headerTitle = $derived(query || $text('embeds.nutrition.search_recipes'));
  let headerSubtitle = $derived(`${$text('embeds.via')} ${provider}`);
</script>

<SearchResultsTemplate
  appId="nutrition"
  skillId="search_recipes"
  maxGridWidth="1100px"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={parseRecipeResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage || $text('chat.an_error_occured')}
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
    <NutritionRecipeEmbedPreview
      id={result.embed_id}
      title={result.title}
      image_url={result.image_url}
      total_time_minutes={result.total_time_minutes}
      difficulty={result.difficulty}
      rating={result.rating}
      rating_count={result.rating_count}
      dietary_tags={result.dietary_tags}
      servings={result.servings}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <NutritionRecipeEmbedFullscreen
      recipe={nav.result}
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
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon='nutrition']) {
    -webkit-mask-image: url('@openmates/ui/static/icons/nutrition.svg');
    mask-image: url('@openmates/ui/static/icons/nutrition.svg');
  }
</style>
