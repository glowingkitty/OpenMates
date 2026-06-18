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

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  interface RecipeResult {
    embed_id: string;
    title?: string;
    description?: string;
    image_url?: string | null;
    recipe_url?: string;
    prep_time_minutes?: number | null;
    cook_time_minutes?: number | null;
    total_time_minutes?: number | null;
    difficulty?: string | null;
    servings?: number | null;
    rating?: number | null;
    rating_count?: number | null;
    ernaehrwert_score?: number | null;
    dietary_tags?: string[];
    categories?: string[];
    ingredients?: Array<{ amount?: string; unit?: string; name: string }>;
    instructions?: Array<{ step?: number; text: string }>;
    nutrition?: {
      calories_kcal?: number;
      protein_g?: number;
      fat_g?: number;
      carbs_g?: number;
      fiber_g?: number;
      sodium_mg?: number;
    };
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
      localResults = Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : [];
      localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
      localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error as string : '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let legacyResults = $derived(localResults);

  function asString(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const trimmed = value.trim();
    return trimmed.length > 0 && trimmed.toLowerCase() !== 'null' ? trimmed : undefined;
  }

  function asNumber(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
      const leadingNumber = value.match(/-?\d+(?:[.,]\d+)?/);
      if (leadingNumber) {
        const parsedLeading = Number(leadingNumber[0].replace(',', '.'));
        if (Number.isFinite(parsedLeading)) return parsedLeading;
      }
    }
    return undefined;
  }

  function parseNutrition(content: Record<string, unknown>): RecipeResult['nutrition'] | undefined {
    const raw = content.nutrition;
    const n = raw && typeof raw === 'object' ? raw as Record<string, unknown> : content;
    return {
      calories_kcal: asNumber(n.calories_kcal ?? n.nutrition_calories_kcal ?? n.calories_per_serving ?? n.nutrition_energy),
      protein_g: asNumber(n.protein_g ?? n.nutrition_protein_g ?? n.nutrition_protein),
      fat_g: asNumber(n.fat_g ?? n.nutrition_fat_g ?? n.nutrition_fat),
      carbs_g: asNumber(n.carbs_g ?? n.nutrition_carbs_g ?? n.nutrition_carbohydrates),
      fiber_g: asNumber(n.fiber_g ?? n.nutrition_fiber_g ?? n.nutrition_fiber),
      sodium_mg: asNumber(n.sodium_mg ?? n.nutrition_sodium_mg ?? n.nutrition_sodium)
    };
  }

  function parseDelimitedList(value: unknown): string[] {
    if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
    const raw = asString(value);
    return raw ? raw.split('|').map((item) => item.trim()).filter(Boolean) : [];
  }

  function parseMergedList(...values: unknown[]): string[] {
    return [...new Set(values.flatMap(parseDelimitedList))];
  }

  function parseIngredients(content: Record<string, unknown>): RecipeResult['ingredients'] {
    const raw = content.ingredients;
    if (typeof raw === 'string') {
      return parseDelimitedList(raw).map((name) => ({ name }));
    }
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
      .map((item) => ({
        amount: asString(item.amount),
        unit: asString(item.unit),
        name: typeof item.name === 'string' ? item.name : ''
      }));
  }

  function parseInstructions(content: Record<string, unknown>): RecipeResult['instructions'] {
    const raw = content.instructions;
    if (typeof raw === 'string') {
      return parseDelimitedList(raw).map((text, index) => ({ step: index + 1, text }));
    }
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
      .map((item) => ({
        step: asNumber(item.step),
        text: typeof item.text === 'string' ? item.text : ''
      }));
  }

  function transformToRecipeResult(embedId: string, content: Record<string, unknown>): RecipeResult {
    return {
      embed_id: asString(content.embed_id) || embedId,
      title: asString(content.title),
      description: asString(content.description),
      image_url: asString(content.image_url) || null,
      recipe_url: asString(content.recipe_url),
      prep_time_minutes: asNumber(content.prep_time_minutes) ?? null,
      cook_time_minutes: asNumber(content.cook_time_minutes) ?? null,
      total_time_minutes: asNumber(content.total_time_minutes) ?? null,
      difficulty: asString(content.difficulty) || null,
      servings: asNumber(content.servings) ?? null,
      rating: asNumber(content.rating) ?? null,
      rating_count: asNumber(content.rating_count) ?? null,
      ernaehrwert_score: asNumber(content.ernaehrwert_score) ?? null,
      dietary_tags: parseMergedList(content.dietary_tags, content.diet_labels, content.health_labels),
      categories: parseMergedList(content.categories, content.cuisine_type, content.meal_type, content.dish_type),
      ingredients: parseIngredients(content),
      instructions: parseInstructions(content),
      nutrition: parseNutrition(content)
    };
  }

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
          transformed.push(transformToRecipeResult(`legacy-${i}-${j}`, groupedItem));
        }
        continue;
      }

      transformed.push(transformToRecipeResult(`legacy-${i}`, item));
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
  childEmbedTransformer={transformToRecipeResult}
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
