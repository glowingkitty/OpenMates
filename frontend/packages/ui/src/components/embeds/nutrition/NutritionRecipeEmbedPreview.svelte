<!--
  frontend/packages/ui/src/components/embeds/nutrition/NutritionRecipeEmbedPreview.svelte

  Preview card for a single nutrition recipe result.
  Uses UnifiedEmbedPreview as the base card. Follows the product card layout pattern:
  text content on left, image thumbnail on right.

  Shows: title, total time, difficulty, dietary tags, optional image.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_PREVIEW_IMAGE = 480;

  interface Props {
    id: string;
    title?: string;
    image_url?: string | null;
    total_time_minutes?: number | null;
    difficulty?: string | null;
    rating?: number | null;
    rating_count?: number | null;
    dietary_tags?: string[];
    servings?: number | null;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    image_url = null,
    total_time_minutes = null,
    difficulty = null,
    rating = null,
    rating_count = null,
    dietary_tags = [],
    servings = null,
    status = 'finished',
    isMobile = false,
    onFullscreen
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

  let cardTitle = $derived(title || 'Recipe');
  let durationText = $derived(formatDuration(total_time_minutes));
  let difficultyText = $derived(formatDifficulty(difficulty));
  let imageUrl = $derived(image_url ? proxyImage(image_url, MAX_WIDTH_PREVIEW_IMAGE) : '');
  let displayTags = $derived((dietary_tags || []).slice(0, 2));

  function handleStop() {
    // Recipe cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="nutrition"
  skillId="search_recipes"
  skillIconName="nutrition"
  {status}
  skillName={cardTitle}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="recipe-preview" class:mobile={isMobileLayout}>
      <div class="recipe-content-row">
        <!-- Text content (left side) -->
        <div class="recipe-text">
          <div class="recipe-title">{cardTitle}</div>

          <!-- Time + difficulty row -->
          {#if durationText || difficultyText}
            <div class="meta-row">
              {#if durationText}
                <span class="meta-item">{durationText}</span>
              {/if}
              {#if difficultyText}
                <span class="meta-item">{difficultyText}</span>
              {/if}
            </div>
          {/if}

          <!-- Rating -->
          {#if rating != null}
            <div class="rating-row">
              <span class="rating">{rating.toFixed(1)}</span>
              {#if rating_count != null}
                <span class="rating-count">({rating_count.toLocaleString()})</span>
              {/if}
            </div>
          {/if}

          <!-- Servings -->
          {#if servings != null}
            <div class="servings">{servings} {$text('embeds.nutrition.servings')}</div>
          {/if}

          <!-- Dietary tags -->
          {#if displayTags.length > 0}
            <div class="tags-row">
              {#each displayTags as tag}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          {/if}
        </div>

        <!-- Image (right side) -->
        {#if imageUrl && !isMobileLayout}
          <div class="recipe-preview-image">
            <img src={imageUrl} alt={cardTitle} loading="lazy" />
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .recipe-preview {
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    justify-content: center;
  }

  .recipe-preview.mobile {
    justify-content: flex-start;
  }

  .recipe-content-row {
    display: flex;
    align-items: stretch;
    flex: 1;
    min-height: 0;
    height: 100%;
    width: 100%;
  }

  .recipe-text {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 0 1 55%;
    min-width: 0;
    align-self: center;
    padding: 2px 0;
  }

  /* Image on right side */
  .recipe-preview-image {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 171px;
    transform: translateX(20px);
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-5);
    overflow: hidden;
  }

  .recipe-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
    box-sizing: border-box;
  }

  .recipe-title {
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .meta-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    flex-wrap: wrap;
  }

  .meta-item {
    font-size: var(--font-size-tiny);
    color: var(--color-grey-60);
    font-weight: 500;
  }

  .meta-item + .meta-item::before {
    content: '\00B7';
    margin-right: var(--spacing-3);
    color: var(--color-grey-40);
  }

  .rating-row {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }

  .rating {
    font-size: var(--font-size-tiny);
    color: #f59e0b;
    font-weight: 600;
  }

  .rating::before {
    content: '\2605 ';
  }

  .rating-count {
    font-size: var(--font-size-tiny);
    color: var(--color-grey-60);
  }

  .servings {
    font-size: var(--font-size-tiny);
    color: var(--color-grey-60);
  }

  .tags-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    margin-top: 1px;
  }

  .tag {
    font-size: var(--font-size-tiny);
    padding: 1px 6px;
    border-radius: var(--radius-4);
    background: rgba(var(--color-primary-rgb), 0.1);
    color: var(--color-primary);
    font-weight: 600;
  }
</style>
