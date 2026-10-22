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
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
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
    resultContext?: 'auto' | 'chat' | 'results';
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
    resultContext = 'auto',
    onFullscreen
  }: Props = $props();

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
  skillIconName="search"
  {status}
  skillName={cardTitle}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  {resultContext}
  resultPreview={true}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <ResultEmbedCard imageTestId="nutrition-recipe-preview-image" title={cardTitle} description={[durationText, difficultyText, servings != null ? `${servings} ${$text('embeds.nutrition.servings')}` : '', ...displayTags].filter(Boolean).join(' · ')} imageUrl={imageUrl} imageAlt={cardTitle}>
      {#snippet facts()}{#if rating != null}<span>★ {rating.toFixed(1)}{#if rating_count != null} ({rating_count.toLocaleString()}){/if}</span>{/if}{/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
