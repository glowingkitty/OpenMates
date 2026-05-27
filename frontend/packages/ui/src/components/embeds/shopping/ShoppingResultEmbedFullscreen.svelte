<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedFullscreen.svelte

  Fullscreen detail view for a single shopping product result.
  Used as child overlay from ShoppingSearchEmbedFullscreen via SearchResultsTemplate.
  Shows product media, pricing details, attributes, and purchase CTA.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_PRODUCT_IMAGE = 1200;

  interface ProductAttributes {
    [key: string]: unknown;
    is_organic?: boolean;
    is_vegan?: boolean;
    is_vegetarian?: boolean;
    is_dairy_free?: boolean;
    is_gluten_free?: boolean;
    is_regional?: boolean;
    is_new?: boolean;
  }

  interface ShoppingResult {
    embed_id: string;
    product_id?: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;
    base_price?: string | null;
    unit?: string | null;
    stock?: number | null;
    availability?: string | null;
    is_salable?: boolean | null;
    variation_id?: string | null;
    color_child_item_ids?: string[];
    was_price_cents?: number | null;
    grammage?: string | null;
    purchase_url?: string;
    image_url?: string | null;
    category_path?: string | null;
    price?: string | null;
    price_amount?: number | null;
    old_price?: string | null;
    old_price_amount?: number | null;
    currency_symbol?: string | null;
    asin?: string;
    rating?: number | null;
    reviews?: number | null;
    prime?: boolean | null;
    delivery?: string[];
    bought_last_month?: string | null;
    provider?: string;
    country?: string;
    attributes?: ProductAttributes;
  }

  interface Props {
    data?: EmbedFullscreenRawData;
    product?: ShoppingResult;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    product: productProp,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
  }

  function asNumber(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return undefined;
  }

  function asBoolean(value: unknown): boolean | undefined {
    if (typeof value === 'boolean') return value;
    if (value === 'true' || value === '1' || value === 1) return true;
    if (value === 'false' || value === '0' || value === 0) return false;
    return undefined;
  }

  function parseAttributes(content: Record<string, unknown>): ProductAttributes | undefined {
    const raw = content.attributes;
    if (!raw || typeof raw !== 'object') return undefined;
    const attrs = raw as Record<string, unknown>;
    return {
      ...attrs,
      is_organic: asBoolean(attrs.is_organic),
      is_vegan: asBoolean(attrs.is_vegan),
      is_vegetarian: asBoolean(attrs.is_vegetarian),
      is_dairy_free: asBoolean(attrs.is_dairy_free),
      is_gluten_free: asBoolean(attrs.is_gluten_free),
      is_regional: asBoolean(attrs.is_regional),
      is_new: asBoolean(attrs.is_new),
    };
  }

  function productFromFullscreenData(rawData: EmbedFullscreenRawData | undefined, fallbackEmbedId: string | undefined): ShoppingResult {
    const content = rawData?.decodedContent ?? {};
    return {
      embed_id: asString(content.embed_id) || fallbackEmbedId || '',
      product_id: asString(content.product_id),
      title: asString(content.title),
      brand: asString(content.brand),
      price_cents: asNumber(content.price_cents) ?? null,
      price_eur: asString(content.price_eur) || null,
      base_price: asString(content.base_price) || null,
      unit: asString(content.unit) || null,
      stock: asNumber(content.stock) ?? null,
      availability: asString(content.availability) || null,
      is_salable: asBoolean(content.is_salable) ?? null,
      variation_id: asString(content.variation_id) || null,
      color_child_item_ids: Array.isArray(content.color_child_item_ids)
        ? (content.color_child_item_ids.filter((item) => typeof item === 'string') as string[])
        : undefined,
      was_price_cents: asNumber(content.was_price_cents) ?? null,
      grammage: asString(content.grammage) || null,
      purchase_url: asString(content.purchase_url) || asString(content.url),
      image_url: asString(content.image_url) || null,
      category_path: asString(content.category_path) || null,
      price: asString(content.price) || null,
      price_amount: asNumber(content.price_amount) ?? null,
      old_price: asString(content.old_price) || null,
      old_price_amount: asNumber(content.old_price_amount) ?? null,
      currency_symbol: asString(content.currency_symbol) || null,
      asin: asString(content.asin),
      rating: asNumber(content.rating) ?? null,
      reviews: asNumber(content.reviews) ?? null,
      prime: asBoolean(content.prime) ?? null,
      delivery: Array.isArray(content.delivery)
        ? (content.delivery.filter((item) => typeof item === 'string') as string[])
        : undefined,
      bought_last_month: asString(content.bought_last_month) || null,
      provider: asString(content.provider),
      country: asString(content.country),
      attributes: parseAttributes(content),
    };
  }

  let product = $derived(productProp ?? productFromFullscreenData(data, embedId));

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
    if (product.price) return product.price;
    if (product.price_eur) return product.price_eur;
    if (product.price_amount != null) return formatAmount(product.price_amount, product.currency_symbol);
    return formatCents(product.price_cents);
  }

  function getDisplayOldPrice(): string {
    if (product.old_price) return product.old_price;
    if (product.old_price_amount != null) return formatAmount(product.old_price_amount, product.currency_symbol);
    return formatCents(product.was_price_cents);
  }

  function hasSale(): boolean {
    if (product.old_price_amount != null && product.price_amount != null) {
      return product.old_price_amount > product.price_amount;
    }
    if (product.was_price_cents != null && product.price_cents != null) {
      return product.was_price_cents > product.price_cents;
    }
    return false;
  }

  function getTags(): string[] {
    const tags: string[] = [];
    const attr = product.attributes;
    if (!attr) return tags;
    if (attr.is_organic) tags.push('Bio');
    if (attr.is_vegan) tags.push('Vegan');
    if (attr.is_vegetarian) tags.push('Vegetarisch');
    if (attr.is_dairy_free) tags.push('Laktosefrei');
    if (attr.is_gluten_free) tags.push('Glutenfrei');
    if (attr.is_regional) tags.push('Regional');
    return tags;
  }

  function formatStock(value: number | null | undefined): string {
    if (value == null || value <= 0) return '';
    return Number.isInteger(value) ? String(value) : value.toFixed(1).replace('.', ',');
  }

  function getAttributeValue(key: string): string {
    const value = product.attributes?.[key];
    return value == null || value === '' ? '' : String(value);
  }

  function getFabricDetails(): { label: string; value: string }[] {
    const details = [
      { label: $text('embeds.shopping.material'), value: getAttributeValue('Material') },
      { label: $text('embeds.shopping.width'), value: getAttributeValue('Stoffbreite (cm)') },
      { label: $text('embeds.shopping.weight'), value: getAttributeValue('Gramm pro Laufmeter') },
      { label: $text('embeds.shopping.motif'), value: getAttributeValue('Motiv') },
      { label: $text('embeds.shopping.usage'), value: getAttributeValue('Verwendung') },
      { label: $text('embeds.shopping.composition'), value: getAttributeValue('Baumwolle %') },
    ];

    return details.filter((detail) => detail.value.length > 0);
  }

  let title = $derived(product.title || product.brand || 'Product');
  let subtitle = $derived(product.brand || product.provider || '');
  let displayPrice = $derived(getDisplayPrice());
  let displayOldPrice = $derived(getDisplayOldPrice());
  let onSale = $derived(hasSale());
  let tags = $derived(getTags());
  let imageUrl = $derived(product.image_url ? proxyImage(product.image_url, MAX_WIDTH_PRODUCT_IMAGE) : '');
  let ratingText = $derived(product.rating != null ? `★ ${product.rating.toFixed(1)}` : '');
  let stockText = $derived(formatStock(product.stock));
  let colorCount = $derived(product.color_child_item_ids?.length ?? 0);
  let fabricDetails = $derived(getFabricDetails());
</script>

<UnifiedEmbedFullscreen
  appId="shopping"
  skillId="search_products"
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if product.purchase_url}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', product.provider || 'Product')} href={product.purchase_url} />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="product-fullscreen">
      <div class="media-column">
        {#if imageUrl}
          <img class="product-image" src={imageUrl} alt={title} loading="lazy" />
        {:else}
          <div class="image-placeholder">🛒</div>
        {/if}
      </div>

      <div class="info-column">
        <h2 class="title">{title}</h2>

        {#if product.brand}
          <div class="brand">{product.brand}</div>
        {/if}

        <div class="price-row">
          {#if displayPrice}
            <span class="price" class:sale={onSale}>{displayPrice}</span>
          {:else}
            <span class="price-unavailable">{$text('embeds.shopping.price_unavailable')}</span>
          {/if}
          {#if onSale && displayOldPrice}
            <span class="old-price">{displayOldPrice}</span>
            <span class="sale-badge">{$text('embeds.shopping.sale')}</span>
          {/if}
        </div>

        {#if product.grammage}
          <div class="grammage">{product.grammage}</div>
        {/if}

        {#if product.base_price || product.unit}
          <div class="detail-grid compact">
            {#if product.base_price}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.base_price')}</span>
                <span class="detail-value">{product.base_price}</span>
              </div>
            {/if}
            {#if product.unit}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.unit')}</span>
                <span class="detail-value">{product.unit}</span>
              </div>
            {/if}
          </div>
        {/if}

        {#if ratingText}
          <div class="rating-row">
            <span class="rating">{ratingText}</span>
            {#if product.reviews != null}
              <span class="reviews">({product.reviews.toLocaleString()})</span>
            {/if}
            {#if product.prime}
              <span class="prime">Prime</span>
            {/if}
          </div>
        {/if}

        {#if product.delivery && product.delivery.length > 0}
          <div class="delivery">{product.delivery[0]}</div>
        {/if}

        {#if product.availability || stockText || colorCount > 0 || product.is_salable != null}
          <div class="detail-grid">
            {#if product.availability}
              <div class="detail-item wide">
                <span class="detail-label">{$text('embeds.shopping.availability')}</span>
                <span class="detail-value">{product.availability}</span>
              </div>
            {/if}
            {#if stockText}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.stock')}</span>
                <span class="detail-value">{stockText}</span>
              </div>
            {/if}
            {#if colorCount > 0}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.colors')}</span>
                <span class="detail-value">{colorCount}</span>
              </div>
            {/if}
            {#if product.is_salable != null}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.status')}</span>
                <span class="detail-value">{product.is_salable ? $text('embeds.shopping.available') : $text('embeds.shopping.not_available')}</span>
              </div>
            {/if}
          </div>
        {/if}

        {#if product.bought_last_month}
          <div class="social-proof">{product.bought_last_month}</div>
        {/if}

        {#if tags.length > 0}
          <div class="tags-row">
            {#each tags as tag}
              <span class="tag">{tag}</span>
            {/each}
          </div>
        {/if}

        {#if fabricDetails.length > 0}
          <div class="fabric-details">
            <h3>{$text('embeds.shopping.fabric_details')}</h3>
            <div class="detail-grid">
              {#each fabricDetails as detail}
                <div class="detail-item">
                  <span class="detail-label">{detail.label}</span>
                  <span class="detail-value">{detail.value}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if product.product_id || product.variation_id}
          <div class="detail-grid compact muted">
            {#if product.product_id}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.product_id')}</span>
                <span class="detail-value">{product.product_id}</span>
              </div>
            {/if}
            {#if product.variation_id}
              <div class="detail-item">
                <span class="detail-label">{$text('embeds.shopping.variation_id')}</span>
                <span class="detail-value">{product.variation_id}</span>
              </div>
            {/if}
          </div>
        {/if}

        {#if product.category_path}
          <div class="category-path">{product.category_path}</div>
        {/if}

      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .product-fullscreen {
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
  }

  .product-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
    max-height: 560px;
    padding: 18px;
    box-sizing: border-box;
  }

  .image-placeholder {
    font-size: 3.25rem;
    opacity: 0.45;
  }

  .info-column {
    background: var(--color-grey-5);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-7);
    padding: var(--spacing-10);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
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

  .brand {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
  }

  .price-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    flex-wrap: wrap;
  }

  .price {
    font-size: var(--font-size-xxl);
    font-weight: 800;
    color: var(--color-font-primary);
    line-height: 1.2;
  }

  .price.sale {
    color: var(--color-error);
  }

  .old-price {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
    text-decoration: line-through;
  }

  .sale-badge {
    font-size: var(--font-size-tiny);
    font-weight: 700;
    color: var(--color-grey-0);
    background: var(--color-error);
    border-radius: 100px;
    padding: var(--spacing-1) var(--spacing-4);
    text-transform: uppercase;
  }

  .price-unavailable {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
    font-style: italic;
  }

  .grammage,
  .delivery,
  .social-proof,
  .category-path {
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.35;
    word-break: break-word;
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--spacing-3);
  }

  .detail-grid.compact {
    gap: var(--spacing-2);
  }

  .detail-grid.muted {
    opacity: 0.78;
  }

  .detail-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: var(--spacing-3);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
  }

  .detail-item.wide {
    grid-column: 1 / -1;
  }

  .detail-label {
    font-size: var(--font-size-tiny);
    color: var(--color-font-secondary);
    font-weight: 600;
  }

  .detail-value {
    font-size: var(--font-size-xs);
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
  }

  .fabric-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    margin-top: var(--spacing-1);
  }

  .fabric-details h3 {
    margin: 0;
    font-size: var(--font-size-small);
    color: var(--color-font-primary);
  }

  .rating-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    flex-wrap: wrap;
  }

  .rating {
    font-size: var(--font-size-xs);
    color: #f59e0b;
    font-weight: 700;
  }

  .reviews {
    font-size: var(--font-size-xxs);
    color: var(--color-font-secondary);
  }

  .prime {
    font-size: var(--font-size-tiny);
    font-weight: 700;
    padding: 2px 7px;
    border-radius: var(--radius-4);
    background: rgba(59, 130, 246, 0.12);
    color: #2563eb;
  }

  .tags-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    margin-top: var(--spacing-1);
  }

  .tag {
    font-size: var(--font-size-tiny);
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 100px;
    background: rgba(var(--color-primary-rgb), 0.1);
    color: var(--color-primary);
  }

  @container fullscreen (max-width: 760px) {
    .product-fullscreen {
      grid-template-columns: 1fr;
      gap: 14px;
      margin-top: var(--spacing-8);
    }

    .media-column {
      min-height: 220px;
    }

    .title {
      font-size: var(--font-size-h3);
    }

    .price {
      font-size: var(--font-size-h2-mobile);
    }

    .detail-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
