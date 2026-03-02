<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingSearchEmbedPreview.svelte

  Preview component for the Shopping Search Products skill embed.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.

  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives query, provider, results directly

  Details content structure:
  - Processing: search query + "via REWE"
  - Finished: search query + product count + price range (lowest price)
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
   * A single product result from the search_products skill.
   * Matches the fields returned by REWEProduct.to_result_dict().
   */
  interface ProductResult {
    type?: string;
    product_id?: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;   // Formatted price, e.g. "1,39 €"
    was_price_cents?: number | null;
    grammage?: string | null;
    purchase_url?: string;
    image_url?: string | null;
    category_path?: string | null;
    total_result_count?: number;
    attributes?: {
      is_organic?: boolean;
      is_vegan?: boolean;
      is_vegetarian?: boolean;
    };
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query (e.g., "bio joghurt") */
    query?: string;
    /** Provider name (e.g., 'REWE') */
    provider?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Product results (for finished state) */
    results?: ProductResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
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
  let localResults = $state<ProductResult[]>([]);
  let localErrorMessage = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'REWE';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
    localErrorMessage = '';
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

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (typeof content.error === 'string') localErrorMessage = content.error;
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as ProductResult[];
      }
    }
  }

  // Skill display info
  let skillName = $derived($text('app_skills.shopping.search_products'));
  const skillIconName = 'search';
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  /**
   * Flatten nested results if needed.
   * Backend returns [{id, results: [...]}] for multi-request responses.
   */
  function flattenResults(rawResults: ProductResult[]): ProductResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: ProductResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: ProductResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    return rawResults;
  }

  let flatResults = $derived(flattenResults(results));

  // Product count display
  let productCount = $derived(flatResults.length);

  // Total result count from first product (if available)
  let totalResultCount = $derived(flatResults.length > 0 ? (flatResults[0].total_result_count ?? flatResults.length) : 0);

  // Lowest price display
  let lowestPriceDisplay = $derived.by(() => {
    if (flatResults.length === 0) return '';
    const prices = flatResults
      .filter(r => r.price_cents != null && r.price_cents > 0)
      .map(r => r.price_cents as number);
    if (prices.length === 0) return '';
    const minCents = Math.min(...prices);
    const formatted = (minCents / 100).toFixed(2).replace('.', ',');
    return `${$text('embeds.from')} ${formatted} €`;
  });

  /** Handle stop button click */
  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error('[ShoppingSearchEmbedPreview] Failed to cancel skill:', error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error('[ShoppingSearchEmbedPreview] Failed to cancel task:', error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="shopping"
  skillId="search_products"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="shopping-search-details" class:mobile={isMobileLayout}>
      <!-- Search query (e.g., "bio joghurt") -->
      <div class="search-query">{query || $text('app_skills.shopping.search_products')}</div>

      <!-- Provider subtitle (e.g., "via REWE") -->
      <div class="search-provider">{viaProvider}</div>

      <!-- Error state -->
      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state: product count + lowest price -->
        <div class="search-results-info">
          {#if productCount > 0}
            <span class="product-count">
              {productCount}{totalResultCount > productCount ? `/${totalResultCount}` : ''} {productCount === 1 ? $text('embeds.shopping.product') : $text('embeds.shopping.products')}
            </span>
          {/if}

          {#if lowestPriceDisplay}
            <span class="price-info">{lowestPriceDisplay}</span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Shopping Search Details Content
     =========================================== */

  .shopping-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }

  .shopping-search-details:not(.mobile) {
    justify-content: center;
  }

  .shopping-search-details.mobile {
    justify-content: flex-start;
  }

  /* Query text */
  .search-query {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .shopping-search-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  /* Provider subtitle */
  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  .shopping-search-details.mobile .search-provider {
    font-size: 12px;
  }

  /* Results info row */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    flex-wrap: wrap;
  }

  .shopping-search-details.mobile .search-results-info {
    margin-top: 2px;
  }

  .product-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .shopping-search-details.mobile .product-count {
    font-size: 12px;
  }

  .price-info {
    font-size: 14px;
    color: var(--color-primary);
    font-weight: 600;
  }

  .shopping-search-details.mobile .price-info {
    font-size: 12px;
  }

  /* Error styling */
  .search-error {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 12px;
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }

  .search-error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-error);
  }

  .search-error-message {
    margin-top: 2px;
    font-size: 12px;
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }
</style>
