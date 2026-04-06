<!--
  frontend/packages/ui/src/components/embeds/nutrition/NutritionSearchEmbedPreview.svelte

  Preview card for the Nutrition Search Recipes skill embed (parent).
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.

  Details content structure:
  - Processing: search query + "via REWE"
  - Finished: search query + recipe count
  - Error: error title + message

  Real-time updates when embed status changes from 'processing' to 'finished'
  are handled by UnifiedEmbedPreview, which subscribes to embedUpdated events.
  This component implements onEmbedDataUpdated to refresh its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  /**
   * A single recipe result from the search_recipes skill.
   * Matches the fields returned by REWERecipe.to_result_dict().
   */
  interface RecipeResult {
    type?: string;
    uid?: string;
    title?: string;
    description?: string;
    image_url?: string;
    total_time_minutes?: number | null;
    difficulty?: string | null;
    rating?: number | null;
    rating_count?: number | null;
    dietary_tags?: string[];
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query (e.g., "vegetarische pasta") */
    query?: string;
    /** Provider name (e.g., 'REWE') */
    provider?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Recipe results (for finished state) */
    results?: RecipeResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated by handleEmbedDataUpdated when embed streams in
  let localQuery = $state<string>('');
  let localProvider = $state<string>('REWE');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let storeResolved = $state(false);
  let localResults = $state<RecipeResult[]>([]);
  let localErrorMessage = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || '';
      localProvider = providerProp || 'REWE';
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
      localErrorMessage = '';
    }
  });

  // Derived display state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the parent component receives and decodes updated embed data.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (typeof content.error === 'string') localErrorMessage = content.error;
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as RecipeResult[];
      }
    }
  }

  // Skill display info
  let skillName = $derived($text('embeds.nutrition.search_recipes'));
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  /**
   * Flatten nested results if needed.
   * Backend returns [{id, results: [...]}] for multi-request responses.
   */
  function flattenResults(rawResults: RecipeResult[]): RecipeResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: RecipeResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: RecipeResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    return rawResults;
  }

  let flatResults = $derived(flattenResults(results));
  let recipeCount = $derived(flatResults.length);

  /** Handle stop button click */
  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error('[NutritionSearchEmbedPreview] Failed to cancel skill:', error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error('[NutritionSearchEmbedPreview] Failed to cancel task:', error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="nutrition"
  skillId="search_recipes"
  skillIconName="nutrition"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="nutrition-search-details" class:mobile={isMobileLayout}>
      <!-- Search query (e.g., "vegetarische pasta") -->
      <div class="ds-search-query">{query || $text('embeds.nutrition.search_recipes')}</div>

      <!-- Provider subtitle (e.g., "via REWE") -->
      <div class="ds-search-provider">{viaProvider}</div>

      <!-- Error state -->
      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state: recipe count -->
        <div class="ds-search-results-info">
          {#if recipeCount > 0}
            <span class="recipe-count">
              {recipeCount} {recipeCount === 1 ? $text('embeds.nutrition.recipe') : $text('embeds.nutrition.recipes')}
            </span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Nutrition Search Details Content
     =========================================== */

  .nutrition-search-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
  }

  .nutrition-search-details:not(.mobile) {
    justify-content: center;
  }

  .nutrition-search-details.mobile {
    justify-content: flex-start;
  }

  /* Base styles for .ds-search-query / .ds-search-provider / .ds-search-results-info
     are generated from frontend/packages/ui/src/tokens/sources/components/search-results.yml
     See docs/architecture/frontend/design-tokens.md (Phase E). */

  .nutrition-search-details.mobile .ds-search-query {
    font-size: var(--font-size-small);
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .nutrition-search-details.mobile .ds-search-provider {
    font-size: var(--font-size-xxs);
  }

  .nutrition-search-details.mobile .ds-search-results-info {
    margin-top: var(--spacing-1);
  }

  .recipe-count {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .nutrition-search-details.mobile .recipe-count {
    font-size: var(--font-size-xxs);
  }

  /* Error styling */
  .search-error {
    margin-top: var(--spacing-3);
    padding: var(--spacing-4) var(--spacing-5);
    border-radius: var(--radius-5);
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }

  .search-error-title {
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-error);
  }

  .search-error-message {
    margin-top: var(--spacing-1);
    font-size: var(--font-size-xxs);
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }
</style>
