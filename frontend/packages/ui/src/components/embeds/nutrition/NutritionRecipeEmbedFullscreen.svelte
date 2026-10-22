<!--
  frontend/packages/ui/src/components/embeds/nutrition/NutritionRecipeEmbedFullscreen.svelte

  Fullscreen detail view for a single nutrition recipe result.
  Used as child overlay from NutritionSearchEmbedFullscreen via SearchResultsTemplate.
  Shows recipe image, ingredients list, step-by-step instructions, and nutrition macros.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import { formatRecipeNutrient, parseRecipeResult, type RecipeResult } from './recipeNutrition';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_RECIPE_IMAGE = 1200;

  interface CommonProps {
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  type Props = CommonProps & (
    { recipe: RecipeResult; data?: never } |
    { data: EmbedFullscreenRawData; recipe?: never }
  );

  let {
    recipe: suppliedRecipe,
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext
  }: Props = $props();

  let recipe = $derived(suppliedRecipe ?? parseRecipeResult(embedId ?? '', data!.decodedContent));

  /** Format minutes into a human-readable duration string */
  function formatDuration(minutes: number | null | undefined): string {
    if (minutes == null || minutes < 0) return '';
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remaining = minutes % 60;
    if (remaining === 0) return `${hours} h`;
    return `${hours} h ${remaining} min`;
  }

  /** Map German difficulty labels to display-friendly text */
  function formatDifficulty(diff: string | null | undefined): string {
    if (!diff) return '';
    const map: Record<string, string> = {
      einfach: 'Easy',
      mittel: 'Medium',
      schwer: 'Hard'
    };
    return map[diff.toLowerCase()] || diff;
  }

  let title = $derived(recipe.title || 'Recipe');
  let subtitle = $derived.by(() => {
    const parts: string[] = [];
    const dur = formatDuration(recipe.total_time_minutes);
    if (dur) parts.push(dur);
    const diff = formatDifficulty(recipe.difficulty);
    if (diff) parts.push(diff);
    if (recipe.servings != null) parts.push(`${recipe.servings} ${$text('embeds.nutrition.servings')}`);
    return parts.join(' \u00B7 ');
  });
  let imageUrl = $derived(recipe.image_url ? proxyImage(recipe.image_url, MAX_WIDTH_RECIPE_IMAGE) : '');
  let ratingText = $derived(recipe.rating != null ? `\u2605 ${recipe.rating.toFixed(1)}` : '');
  let hasNutrition = $derived(
    recipe.nutrition != null &&
    (recipe.nutrition.calories_kcal != null ||
      recipe.nutrition.protein_g != null ||
      recipe.nutrition.fat_g != null ||
      recipe.nutrition.carbs_g != null)
  );
  let failedImage = $state<string>();
  function visibleText(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined;
  }
  function visibleNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }
  // Supplied recipes can contain extra storage fields; project nested records too.
  let visibleContext = $derived({
    title: visibleText(title), description: visibleText(recipe.description), recipe_url: visibleText(recipe.recipe_url),
    total_time_minutes: visibleNumber(recipe.total_time_minutes), difficulty: visibleText(recipe.difficulty),
    servings: visibleNumber(recipe.servings), rating: visibleNumber(recipe.rating), rating_count: visibleNumber(recipe.rating_count),
    ernaehrwert_score: visibleNumber(recipe.ernaehrwert_score),
    dietary_tags: Array.isArray(recipe.dietary_tags) ? recipe.dietary_tags.filter((entry): entry is string => typeof entry === 'string') : [],
    categories: Array.isArray(recipe.categories) ? recipe.categories.filter((entry): entry is string => typeof entry === 'string') : [],
    ingredients: Array.isArray(recipe.ingredients) ? recipe.ingredients.map((entry) => ({
      amount: visibleText(entry.amount), unit: visibleText(entry.unit), name: visibleText(entry.name),
    })) : [],
    instructions: Array.isArray(recipe.instructions) ? recipe.instructions.map((entry) => ({ text: visibleText(entry.text) })) : [],
    nutrition: {
      calories_kcal: visibleNumber(recipe.nutrition?.calories_kcal), protein_g: visibleNumber(recipe.nutrition?.protein_g),
      fat_g: visibleNumber(recipe.nutrition?.fat_g), carbs_g: visibleNumber(recipe.nutrition?.carbs_g),
    },
  });
</script>

<ResultEmbedFullscreen appId="nutrition" skillId="search_recipes" skillIconName="search" embedHeaderTitle={title} embedHeaderSubtitle={subtitle} result={visibleContext} media={imageUrl && failedImage !== imageUrl ? resultMedia : undefined} {onClose} currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}>
  {#snippet embedHeaderCta()}{#if recipe.recipe_url}<EmbedHeaderCtaButton label={$text('embeds.nutrition.view_source')} href={recipe.recipe_url} />{/if}{/snippet}
  {#snippet summary()}
    {#if recipe.total_time_minutes != null}<ResultEmbedInfo icon="clock" label={$text('common.duration')} value={formatDuration(recipe.total_time_minutes)}><p>{formatDuration(recipe.total_time_minutes)}</p></ResultEmbedInfo>{/if}
    {#if recipe.servings != null}<ResultEmbedInfo icon="users" label={$text('embeds.nutrition.servings')} value={`${recipe.servings} ${$text('embeds.nutrition.servings')}`}><p>{recipe.servings} {$text('embeds.nutrition.servings')}</p></ResultEmbedInfo>{/if}
    {#if recipe.rating != null}<ResultEmbedInfo icon="star" label={$text('result_embed.rating')} value={ratingText}><p>{ratingText}{#if recipe.rating_count != null} ({recipe.rating_count}){/if}</p></ResultEmbedInfo>{/if}
  {/snippet}
  {#snippet resultMedia()}{#if imageUrl}<img class="recipe-image" data-testid="nutrition-recipe-image" src={imageUrl} alt={title} loading="lazy" onerror={() => { failedImage = imageUrl; }} />{/if}{/snippet}
  {#snippet detailContent()}
    <div class="recipe-details" data-testid="nutrition-recipe-details">
      {#if recipe.description}<div class="description"><MarkdownContent content={recipe.description} /></div>{/if}
      <div class="result-icon-row">
        {#if recipe.difficulty}<ResultEmbedInfo icon="chef-hat" label={$text('result_embed.difficulty')} value={formatDifficulty(recipe.difficulty)}><p>{formatDifficulty(recipe.difficulty)}</p></ResultEmbedInfo>{/if}
        {#if recipe.dietary_tags?.length}<div data-testid="nutrition-recipe-tags"><ResultEmbedInfo icon="leaf" label={$text('result_embed.dietary')}>{#each recipe.dietary_tags as tag}<p>{tag}</p>{/each}</ResultEmbedInfo></div>{/if}
        {#if recipe.categories?.length}<div data-testid="nutrition-recipe-categories"><ResultEmbedInfo icon="tags" label={$text('result_embed.categories')}>{#each recipe.categories as category}<p>{category}</p>{/each}</ResultEmbedInfo></div>{/if}
        {#if recipe.ernaehrwert_score != null}<ResultEmbedInfo icon="heart" label={$text('embeds.nutrition.health_score')} value={`${recipe.ernaehrwert_score}/10`}><p>{$text('embeds.nutrition.health_score')}: {recipe.ernaehrwert_score}/10</p></ResultEmbedInfo>{/if}
      </div>
        <!-- Ingredients -->
        {#if recipe.ingredients && recipe.ingredients.length > 0}
          <div class="section">
            <h3 class="section-title">{$text('embeds.nutrition.ingredients')}</h3>
            <ul class="ingredients-list">
              {#each recipe.ingredients as ingredient}
                <li class="ingredient-item">
                  {#if ingredient.amount || ingredient.unit}
                    <span class="ingredient-amount">
                      {ingredient.amount || ''}{ingredient.unit ? ` ${ingredient.unit}` : ''}
                    </span>
                  {/if}
                  <span class="ingredient-name">{ingredient.name}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Instructions -->
        {#if recipe.instructions && recipe.instructions.length > 0}
          <div class="section">
            <h3 class="section-title">{$text('embeds.nutrition.instructions')}</h3>
            <ol class="instructions-list">
              {#each recipe.instructions as instruction}
                <li class="instruction-step">
                  <span class="instruction-text">{instruction.text}</span>
                </li>
              {/each}
            </ol>
          </div>
        {/if}

      {#if hasNutrition}<section class="section"><h3 class="section-title">{$text('embeds.nutrition.nutrition_info')}</h3><div class="nutrition-grid">
        {#if recipe.nutrition?.calories_kcal != null}<div class="nutrition-item"><span class="nutrition-value">{formatRecipeNutrient(recipe.nutrition.calories_kcal)}</span><span class="nutrition-label">kcal</span></div>{/if}
        {#each [{ key: 'protein_g', label: $text('embeds.nutrition.protein') }, { key: 'fat_g', label: $text('embeds.nutrition.fat') }, { key: 'carbs_g', label: $text('embeds.nutrition.carbs') }] as nutrient}
          {@const value = recipe.nutrition?.[nutrient.key as 'protein_g' | 'fat_g' | 'carbs_g']}
          {#if value != null}<div class="nutrition-item"><span class="nutrition-value">{formatRecipeNutrient(value)}g</span><span class="nutrition-label">{nutrient.label}</span></div>{/if}
        {/each}
      </div></section>{/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>
<style>
 .recipe-image { display:block; width:100%; height:auto; max-height:65vh; object-fit:contain; }
 .recipe-details { width:100%; display:flex; flex-direction:column; gap:var(--spacing-8); }
 .description { font-size:var(--font-size-small); }
  /* Sections */
  .section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .section-title {
    margin: 0;
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-font-primary);
    padding-bottom: var(--spacing-2);
    border-bottom: 1px solid var(--color-grey-20);
  }

  /* Ingredients */
  .ingredients-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .ingredient-item {
    display: flex;
    gap: var(--spacing-3);
    font-size: var(--font-size-small);
    padding: var(--spacing-2) 0;
    border-bottom: 1px solid var(--color-grey-10);
  }

  .ingredient-amount {
    font-weight: 600;
    color: var(--color-font-primary);
    min-width: 80px;
    flex-shrink: 0;
  }

  .ingredient-name {
    color: var(--color-font-secondary);
  }

  /* Instructions */
  .instructions-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
    counter-reset: step;
  }

  .instruction-step {
    display: flex;
    gap: var(--spacing-5);
    counter-increment: step;
  }

  .instruction-step::before {
    content: counter(step);
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--color-app-nutrition);
    color: var(--color-grey-0);
    font-size: var(--font-size-xs);
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: 1px;
  }

  .instruction-text {
    font-size: var(--font-size-small);
    color: var(--color-font-primary);
    line-height: 1.6;
    flex: 1;
    min-width: 0;
  }

 .nutrition-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:var(--spacing-4); }
 .nutrition-item { display:flex; flex-direction:column; align-items:center; gap:var(--spacing-2); padding:var(--spacing-3); background:var(--color-grey-0); border-radius:var(--radius-4); }
 .nutrition-value { font-size:var(--font-size-p); font-weight:650; }
 .nutrition-label { font-size:var(--font-size-tiny); color:var(--color-font-secondary); }
 @container fullscreen (max-width: 430px) { .nutrition-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
