<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingSearchEmbedFullscreen.svelte

  Fullscreen view for the Shopping Search Products skill embed.
  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Header with search query and "via REWE"
  - Product cards grid (auto-responsive columns)
  - Consistent BasicInfosBar at the bottom
  - Top bar with share and minimize buttons

  Each product card displays:
  - Product title + brand
  - Current price (price_eur)
  - Grammage / unit price
  - Sale badge if was_price_cents > price_cents
  - Dietary tags (organic, vegan, vegetarian)
  - Buy link to shop.rewe.de
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * A single product result. Matches REWEProduct.to_result_dict() output.
   */
  interface ProductResult {
    type?: string;
    product_id?: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;
    was_price_cents?: number | null;
    grammage?: string | null;
    deposit_cents?: number | null;
    purchase_url?: string;
    image_url?: string | null;
    category_path?: string | null;
    total_result_count?: number;
    search_rank?: number;
    attributes?: {
      is_organic?: boolean;
      is_vegan?: boolean;
      is_vegetarian?: boolean;
      is_dairy_free?: boolean;
      is_gluten_free?: boolean;
      is_new?: boolean;
      is_regional?: boolean;
      is_lowest_price?: boolean;
    };
  }

  interface Props {
    /** Search query (e.g., "bio joghurt") */
    query?: string;
    /** Provider name (e.g., 'REWE') */
    provider?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Product results (legacy flat format — used when embedIds not provided) */
    results?: ProductResult[];
    /** Close handler */
    onClose: () => void;
    /** Optional embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // Local reactive state — initialized to defaults, synced from props via $effect below
  let localQuery = $state<string>('');
  let localProvider = $state<string>('REWE');
  let localResults = $state<ProductResult[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state<string>('');

  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'REWE';
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });

  // Derived state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let results = $derived(localResults);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));

  let skillName = $derived($text('app_skills.shopping.search_products'));
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (Array.isArray(content.results)) localResults = content.results as ProductResult[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  /**
   * Flatten nested grouped results (backend wraps each request as {id, results: [...]}).
   */
  function flattenResults(rawResults: ProductResult[]): ProductResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: ProductResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: ProductResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) flattened.push(...entry.results);
      }
      return flattened;
    }
    return rawResults;
  }

  let flatResults = $derived(flattenResults(results));

  /**
   * Format price in cents to "€ 1,39" display string.
   */
  function formatPrice(cents: number | null | undefined): string {
    if (cents == null || cents <= 0) return '';
    return `${(cents / 100).toFixed(2).replace('.', ',')} €`;
  }

  /**
   * Check if a product is on sale (was_price > current_price).
   */
  function isOnSale(product: ProductResult): boolean {
    return (
      product.was_price_cents != null &&
      product.price_cents != null &&
      product.was_price_cents > product.price_cents
    );
  }

  /**
   * Get top dietary tags for a product (max 3).
   */
  function getDietaryTags(product: ProductResult): string[] {
    const tags: string[] = [];
    const attr = product.attributes;
    if (!attr) return tags;
    if (attr.is_organic) tags.push('Bio');
    if (attr.is_vegan) tags.push('Vegan');
    if (attr.is_vegetarian) tags.push('Vegetarisch');
    if (attr.is_dairy_free) tags.push('Laktosefrei');
    if (attr.is_gluten_free) tags.push('Glutenfrei');
    if (attr.is_regional) tags.push('Regional');
    return tags.slice(0, 3);
  }
</script>

<!-- Product results fullscreen view -->
<UnifiedEmbedFullscreen
  appId="shopping"
  skillId="search_products"
  title=""
  onClose={onClose}
  skillIconName="search"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <!-- Header with query and provider -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>

    <!-- Error state -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">{$text('embeds.search_failed')}</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else if flatResults.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results')}</p>
      </div>
    {:else}
      <!-- Product cards grid -->
      <div class="products-grid">
        {#each flatResults as product (product.product_id ?? product.title)}
          {@const salePrice = isOnSale(product)}
          {@const tags = getDietaryTags(product)}
          <a
            class="product-card"
            href={product.purchase_url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={product.title}
          >
            <!-- Product image -->
            <div class="product-image-container">
              {#if product.image_url}
                <img
                  class="product-image"
                  src={product.image_url}
                  alt={product.title || 'Product'}
                  loading="lazy"
                />
              {:else}
                <div class="product-image-placeholder" aria-hidden="true">
                  <span class="placeholder-icon">🛒</span>
                </div>
              {/if}
              {#if salePrice}
                <div class="sale-badge">{$text('embeds.shopping.sale')}</div>
              {/if}
              {#if product.attributes?.is_new}
                <div class="new-badge">{$text('embeds.shopping.new')}</div>
              {/if}
            </div>

            <!-- Product info -->
            <div class="product-info">
              <div class="product-title">{product.title || ''}</div>

              {#if product.brand}
                <div class="product-brand">{product.brand}</div>
              {/if}

              <!-- Price row -->
              <div class="product-price-row">
                {#if product.price_eur}
                  <span class="product-price" class:sale={salePrice}>
                    {product.price_eur}
                  </span>
                {:else}
                  <span class="product-price-unavailable">
                    {$text('embeds.shopping.price_unavailable')}
                  </span>
                {/if}
                {#if salePrice && product.was_price_cents}
                  <span class="product-was-price">
                    {formatPrice(product.was_price_cents)}
                  </span>
                {/if}
              </div>

              <!-- Grammage / unit price -->
              {#if product.grammage}
                <div class="product-grammage">{product.grammage}</div>
              {/if}

              <!-- Dietary tags -->
              {#if tags.length > 0}
                <div class="product-tags">
                  {#each tags as tag}
                    <span class="product-tag">{tag}</span>
                  {/each}
                </div>
              {/if}
            </div>
          </a>
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Fullscreen Header
     =========================================== */

  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 32px;
    padding: 0 16px;
    text-align: center;
  }

  .search-query {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .search-provider {
    font-size: 16px;
    color: var(--color-font-secondary);
    margin-top: 8px;
  }

  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 20px;
    }

    .search-query {
      font-size: 20px;
    }

    .search-provider {
      font-size: 14px;
    }
  }

  /* ===========================================
     States
     =========================================== */

  .no-results,
  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
    margin-bottom: 8px;
  }

  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }

  /* ===========================================
     Products Grid
     =========================================== */

  .products-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }

  @container fullscreen (max-width: 500px) {
    .products-grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }
  }

  /* ===========================================
     Product Card
     =========================================== */

  .product-card {
    display: flex;
    flex-direction: column;
    border-radius: 16px;
    background-color: var(--color-surface-elevated);
    border: 1px solid var(--color-border-light);
    overflow: hidden;
    text-decoration: none;
    color: inherit;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    cursor: pointer;
  }

  .product-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  }

  /* Product image */
  .product-image-container {
    position: relative;
    width: 100%;
    aspect-ratio: 1 / 1;
    background-color: var(--color-surface-subtle);
    overflow: hidden;
  }

  .product-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
    padding: 8px;
  }

  .product-image-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  .placeholder-icon {
    font-size: 32px;
    opacity: 0.4;
  }

  /* Badges */
  .sale-badge,
  .new-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .sale-badge {
    background-color: var(--color-error);
    color: white;
  }

  .new-badge {
    background-color: var(--color-primary);
    color: white;
    top: 8px;
    right: 8px;
  }

  /* Both badges: stack vertically */
  .sale-badge + .new-badge {
    top: 32px;
  }

  /* Product info block */
  .product-info {
    padding: 12px;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .product-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .product-brand {
    font-size: 12px;
    color: var(--color-font-secondary);
  }

  /* Price row */
  .product-price-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
    margin-top: 2px;
  }

  .product-price {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-font-primary);
  }

  .product-price.sale {
    color: var(--color-error);
  }

  .product-was-price {
    font-size: 12px;
    color: var(--color-font-secondary);
    text-decoration: line-through;
  }

  .product-price-unavailable {
    font-size: 12px;
    color: var(--color-font-secondary);
    font-style: italic;
  }

  /* Grammage */
  .product-grammage {
    font-size: 11px;
    color: var(--color-font-secondary);
    line-height: 1.3;
  }

  /* Dietary tags */
  .product-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }

  .product-tag {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 10px;
    background-color: rgba(var(--color-primary-rgb), 0.1);
    color: var(--color-primary);
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
</style>
