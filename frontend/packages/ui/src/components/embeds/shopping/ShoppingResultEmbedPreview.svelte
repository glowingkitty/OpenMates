<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedPreview.svelte

  Preview card for a single shopping product result.
  Uses UnifiedEmbedPreview as the base card and mirrors the child-card pattern
  used by other search fullscreens (images/travel/events/web).

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_PREVIEW_IMAGE = 480;

  interface ProductAttributes {
    is_organic?: boolean;
    is_vegan?: boolean;
    is_vegetarian?: boolean;
    is_dairy_free?: boolean;
    is_gluten_free?: boolean;
    is_regional?: boolean;
    is_new?: boolean;
  }

  interface Props {
    id: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;
    was_price_cents?: number | null;
    grammage?: string | null;
    image_url?: string | null;
    old_price?: string | null;
    old_price_amount?: number | null;
    price?: string | null;
    price_amount?: number | null;
    currency_symbol?: string | null;
    attributes?: ProductAttributes;
    rating?: number | null;
    reviews?: number | null;
    prime?: boolean | null;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    brand,
    price_cents = null,
    price_eur = null,
    was_price_cents = null,
    grammage = null,
    image_url = null,
    old_price = null,
    old_price_amount = null,
    price = null,
    price_amount = null,
    currency_symbol = null,
    attributes,
    rating = null,
    reviews = null,
    prime = null,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  function formatCents(value: number | null | undefined): string {
    if (value == null || value <= 0) return '';
    return `${(value / 100).toFixed(2).replace('.', ',')} €`;
  }

  function formatAmount(value: number | null | undefined, symbol?: string | null): string {
    if (value == null || value <= 0) return '';
    const currency = symbol || '€';
    const amount = currency === '€' ? value.toFixed(2).replace('.', ',') : value.toFixed(2);
    return `${currency}${amount}`;
  }

  function getDisplayPrice(): string {
    if (price) return price;
    if (price_eur) return price_eur;
    if (price_amount != null) return formatAmount(price_amount, currency_symbol);
    return formatCents(price_cents);
  }

  function getDisplayOldPrice(): string {
    if (old_price) return old_price;
    if (old_price_amount != null) return formatAmount(old_price_amount, currency_symbol);
    return formatCents(was_price_cents);
  }

  function hasSale(): boolean {
    if (old_price_amount != null && price_amount != null) {
      return old_price_amount > price_amount;
    }
    if (was_price_cents != null && price_cents != null) {
      return was_price_cents > price_cents;
    }
    return false;
  }

  function getTags(): string[] {
    const tags: string[] = [];
    if (!attributes) return tags;
    if (attributes.is_organic) tags.push('Bio');
    if (attributes.is_vegan) tags.push('Vegan');
    if (attributes.is_vegetarian) tags.push('Vegetarisch');
    if (attributes.is_dairy_free) tags.push('Laktosefrei');
    if (attributes.is_gluten_free) tags.push('Glutenfrei');
    if (attributes.is_regional) tags.push('Regional');
    return tags.slice(0, 2);
  }

  let cardTitle = $derived(title || brand || 'Product');
  let displayPrice = $derived(getDisplayPrice());
  let displayOldPrice = $derived(getDisplayOldPrice());
  let onSale = $derived(hasSale());
  let tags = $derived(getTags());
  let imageUrl = $derived(image_url ? proxyImage(image_url, MAX_WIDTH_PREVIEW_IMAGE) : '');

  function handleStop() {
    // Product cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="shopping"
  skillId="search_products"
  skillIconName="search"
  {status}
  skillName={cardTitle}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="product-preview" class:mobile={isMobileLayout}>
      <div class="product-content-row">
        <!-- Text content (left side) -->
        <div class="product-text">
          <div class="product-title">{cardTitle}</div>
          {#if brand}
            <div class="product-brand">{brand}</div>
          {/if}

          <div class="price-row">
            {#if displayPrice}
              <span class="product-price" class:sale={onSale}>{displayPrice}</span>
            {:else}
              <span class="no-price">{$text('embeds.shopping.price_unavailable')}</span>
            {/if}
            {#if onSale && displayOldPrice}
              <span class="old-price">{displayOldPrice}</span>
            {/if}
          </div>

          {#if grammage}
            <div class="grammage">{grammage}</div>
          {/if}

          {#if rating != null}
            <div class="rating-row">
              <span class="rating">★ {rating.toFixed(1)}</span>
              {#if reviews != null}
                <span class="reviews">({reviews.toLocaleString()})</span>
              {/if}
              {#if prime}
                <span class="prime">Prime</span>
              {/if}
            </div>
          {/if}

          {#if tags.length > 0}
            <div class="tags-row">
              {#each tags as tag}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          {/if}
        </div>

        <!-- Image (right side) -->
        {#if imageUrl && !isMobileLayout}
          <div class="product-preview-image">
            {#if onSale}
              <span class="badge badge-sale">{$text('embeds.shopping.sale')}</span>
            {/if}
            {#if attributes?.is_new}
              <span class="badge badge-new">{$text('embeds.shopping.new')}</span>
            {/if}
            <img src={imageUrl} alt={cardTitle} loading="lazy" />
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .product-preview {
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    justify-content: center;
  }

  .product-preview.mobile {
    justify-content: flex-start;
  }

  .product-content-row {
    display: flex;
    align-items: stretch;
    flex: 1;
    min-height: 0;
    height: 100%;
    width: 100%;
  }

  .product-text {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 0 1 55%;
    min-width: 0;
    align-self: center;
    padding: 2px 0;
  }

  /* Image on right side */
  .product-preview-image {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 171px;
    transform: translateX(20px);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-10);
  }

  .product-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
    padding: 8px;
    box-sizing: border-box;
  }

  .badge {
    position: absolute;
    top: 6px;
    right: 26px;
    padding: 2px 7px;
    border-radius: 100px;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    z-index: 1;
  }

  .badge-sale {
    background: var(--color-error);
  }

  .badge-new {
    background: var(--color-primary);
    top: 30px;
  }

  .product-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .product-brand {
    font-size: 11px;
    color: var(--color-grey-60);
  }

  .price-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .product-price {
    font-size: 15px;
    font-weight: 700;
    color: var(--color-grey-100);
  }

  .product-price.sale {
    color: var(--color-error);
  }

  .old-price {
    font-size: 11px;
    color: var(--color-grey-60);
    text-decoration: line-through;
  }

  .no-price {
    font-size: 11px;
    color: var(--color-grey-60);
    font-style: italic;
  }

  .grammage {
    font-size: 11px;
    color: var(--color-grey-60);
  }

  .rating-row {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }

  .rating {
    font-size: 11px;
    color: #f59e0b;
    font-weight: 600;
  }

  .reviews {
    font-size: 10px;
    color: var(--color-grey-60);
  }

  .prime {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 5px;
    border-radius: 10px;
    background: rgba(59, 130, 246, 0.12);
    color: #2563eb;
  }

  .tags-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 1px;
  }

  .tag {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 10px;
    background: rgba(var(--color-primary-rgb), 0.1);
    color: var(--color-primary);
    font-weight: 600;
  }
</style>
