<!--
  frontend/packages/ui/src/components/embeds/nutrition/NutritionRecipeEmbedFullscreen.svelte

  Fullscreen detail view for a single nutrition recipe result.
  Used as child overlay from NutritionSearchEmbedFullscreen via SearchResultsTemplate.
  Shows recipe image, ingredients list, step-by-step instructions, and nutrition macros.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_RECIPE_IMAGE = 1200;

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
    };
  }

  interface Props {
    recipe: RecipeResult;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    recipe,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext
  }: Props = $props();

  /** Format minutes into a human-readable duration string */
  function formatDuration(minutes: number | null | undefined): string {
    if (minutes == null || minutes <= 0) return '';
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
</script>

<UnifiedEmbedFullscreen
  appId="nutrition"
  skillId="search_recipes"
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  skillIconName="nutrition"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if recipe.recipe_url}
      <EmbedHeaderCtaButton label={$text('embeds.nutrition.view_on_rewe')} href={recipe.recipe_url} />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="recipe-fullscreen">
      <!-- Hero image -->
      <div class="media-column">
        {#if imageUrl}
          <img class="recipe-image" src={imageUrl} alt={title} loading="lazy" />
        {:else}
          <div class="image-placeholder">🍳</div>
        {/if}
      </div>

      <div class="info-column">
        <h2 class="title">{title}</h2>

        {#if recipe.description}
          <div class="description">
            <MarkdownContent content={recipe.description} />
          </div>
        {/if}

        <!-- Meta row: time, difficulty, servings, rating -->
        <div class="meta-row">
          {#if recipe.total_time_minutes}
            <span class="meta-chip">{formatDuration(recipe.total_time_minutes)}</span>
          {/if}
          {#if recipe.difficulty}
            <span class="meta-chip">{formatDifficulty(recipe.difficulty)}</span>
          {/if}
          {#if recipe.servings != null}
            <span class="meta-chip">{recipe.servings} {$text('embeds.nutrition.servings')}</span>
          {/if}
          {#if ratingText}
            <span class="meta-chip rating">{ratingText}{#if recipe.rating_count != null} ({recipe.rating_count}){/if}</span>
          {/if}
          {#if recipe.ernaehrwert_score != null}
            <span class="meta-chip health-score">{$text('embeds.nutrition.health_score')}: {recipe.ernaehrwert_score}/10</span>
          {/if}
        </div>

        <!-- Dietary tags -->
        {#if recipe.dietary_tags && recipe.dietary_tags.length > 0}
          <div class="tags-row">
            {#each recipe.dietary_tags as tag}
              <span class="tag">{tag}</span>
            {/each}
          </div>
        {/if}

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

        <!-- Nutrition macros -->
        {#if hasNutrition}
          <div class="section">
            <h3 class="section-title">{$text('embeds.nutrition.nutrition_info')}</h3>
            <div class="nutrition-grid">
              {#if recipe.nutrition?.calories_kcal != null}
                <div class="nutrition-item">
                  <span class="nutrition-value">{recipe.nutrition.calories_kcal}</span>
                  <span class="nutrition-label">kcal</span>
                </div>
              {/if}
              {#if recipe.nutrition?.protein_g != null}
                <div class="nutrition-item">
                  <span class="nutrition-value">{recipe.nutrition.protein_g}g</span>
                  <span class="nutrition-label">{$text('embeds.nutrition.protein')}</span>
                </div>
              {/if}
              {#if recipe.nutrition?.fat_g != null}
                <div class="nutrition-item">
                  <span class="nutrition-value">{recipe.nutrition.fat_g}g</span>
                  <span class="nutrition-label">{$text('embeds.nutrition.fat')}</span>
                </div>
              {/if}
              {#if recipe.nutrition?.carbs_g != null}
                <div class="nutrition-item">
                  <span class="nutrition-value">{recipe.nutrition.carbs_g}g</span>
                  <span class="nutrition-label">{$text('embeds.nutrition.carbs')}</span>
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .recipe-fullscreen {
    display: grid;
    grid-template-columns: minmax(280px, 1.1fr) minmax(320px, 1fr);
    gap: var(--spacing-10);
    width: min(1040px, calc(100% - 24px));
    margin: 24px auto 120px;
  }

  .media-column {
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-7);
    min-height: 320px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    position: sticky;
    top: 24px;
    align-self: start;
  }

  .recipe-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    max-height: 560px;
    box-sizing: border-box;
  }

  .image-placeholder {
    font-size: 3.25rem;
    opacity: 0.45;
  }

  .info-column {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    min-width: 0;
  }

  .title {
    margin: 0;
    font-size: var(--font-size-h2-mobile);
    font-weight: 700;
    line-height: 1.25;
    color: var(--color-font-primary);
    word-break: break-word;
  }

  .description {
    margin: 0;
  }
  .description :global(.markdown-content) {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
    line-height: 1.5;
  }

  /* Meta chips row */
  .meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
  }

  .meta-chip {
    font-size: var(--font-size-xs);
    font-weight: 500;
    padding: var(--spacing-2) var(--spacing-5);
    border-radius: 100px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
    color: var(--color-font-secondary);
  }

  .meta-chip.rating {
    color: #f59e0b;
    font-weight: 700;
  }

  .meta-chip.health-score {
    background: rgba(34, 197, 94, 0.1);
    border-color: rgba(34, 197, 94, 0.3);
    color: #16a34a;
  }

  /* Tags */
  .tags-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
  }

  .tag {
    font-size: var(--font-size-tiny);
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 100px;
    background: rgba(var(--color-primary-rgb), 0.1);
    color: var(--color-primary);
  }

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

  /* Nutrition grid */
  .nutrition-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--spacing-4);
  }

  .nutrition-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-1);
    padding: var(--spacing-5);
    border-radius: var(--radius-5);
    background: var(--color-grey-5);
    border: 1px solid var(--color-grey-20);
  }

  .nutrition-value {
    font-size: var(--font-size-h3);
    font-weight: 700;
    color: var(--color-font-primary);
  }

  .nutrition-label {
    font-size: var(--font-size-tiny);
    color: var(--color-font-secondary);
    text-transform: capitalize;
  }

  @container fullscreen (max-width: 760px) {
    .recipe-fullscreen {
      grid-template-columns: 1fr;
      gap: 14px;
      margin-top: var(--spacing-8);
    }

    .media-column {
      min-height: 220px;
      position: static;
    }

    .title {
      font-size: var(--font-size-h3);
    }

    .nutrition-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
