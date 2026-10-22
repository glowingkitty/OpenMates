<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedFullscreen.svelte

  Fullscreen detail view for a single shopping product result.
  Used as child overlay from ShoppingSearchEmbedFullscreen via SearchResultsTemplate.
  Shows product media, pricing details, attributes, and purchase CTA.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { normalizeShoppingProductImages } from './shoppingProductImages';
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
    image_urls?: string[] | string | null;
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
    if (typeof value === 'string' && value.trim()) {
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
      image_url: asString(content.image_url) || normalizeShoppingProductImages(content.image_urls)[0] || null,
      image_urls: normalizeShoppingProductImages(content.image_urls, content.image_url),
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
    if (value == null || value < 0) return '';
    return `${(value / 100).toFixed(2).replace('.', ',')} €`;
  }

  function formatAmount(value: number | null | undefined, symbol?: string | null): string {
    if (value == null || value < 0) return '';
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

  function formatStock(value: number | null | undefined): string {
    if (value == null || value < 0) return '';
    return Number.isInteger(value) ? String(value) : value.toFixed(1).replace('.', ',');
  }

  function attributeLabel(key: string): string {
    const known: Record<string, string> = {
      is_organic: $text('result_embed.organic'), is_vegan: $text('result_embed.vegan'),
      is_vegetarian: $text('result_embed.vegetarian'), is_dairy_free: $text('result_embed.dairy_free'),
      is_gluten_free: $text('result_embed.gluten_free'), is_regional: $text('result_embed.regional'),
      is_new: $text('embeds.shopping.new'),
    };
    return known[key] || key;
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
  let imageUrls = $derived(normalizeShoppingProductImages(product.image_urls, product.image_url));
  let selectedImage = $state(0);
  let failedImages = $state<string[]>([]);
  $effect(() => {
    // Child-product navigation reuses this viewer: reset media with its identity/data.
    void product.embed_id;
    void imageUrls;
    selectedImage = 0;
    failedImages = [];
  });
  let activeImage = $derived(imageUrls[selectedImage]);
  let imageUrl = $derived(activeImage ? proxyImage(activeImage, MAX_WIDTH_PRODUCT_IMAGE) : '');

  function selectImage(event: KeyboardEvent, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % imageUrls.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + imageUrls.length) % imageUrls.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = imageUrls.length - 1;
    else return;
    event.preventDefault();
    event.stopPropagation();
    selectedImage = next;
    const controls = (event.currentTarget as HTMLButtonElement).parentElement;
    controls?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();
  }
  let ratingText = $derived(product.rating != null ? `★ ${product.rating.toFixed(1)}` : '');
  let stockText = $derived(formatStock(product.stock));
  let colorCount = $derived(product.color_child_item_ids?.length ?? 0);
  let fabricDetails = $derived(getFabricDetails());
  // Only fields displayed by this result may cross the follow-up request boundary.
  let visibleContext = $derived({
    title: asString(title), provider: asString(product.provider), brand: asString(product.brand),
    purchase_url: asString(product.purchase_url), price: asString(displayPrice),
    old_price: onSale ? asString(displayOldPrice) : undefined,
    grammage: asString(product.grammage), base_price: asString(product.base_price), unit: asString(product.unit),
    rating: asNumber(product.rating), reviews: asNumber(product.reviews), stock: asNumber(product.stock),
    availability: asString(product.availability), is_salable: asBoolean(product.is_salable), prime: asBoolean(product.prime),
    delivery: Array.isArray(product.delivery) ? product.delivery.filter((entry): entry is string => typeof entry === 'string') : [],
    category_path: asString(product.category_path), product_id: asString(product.product_id), variation_id: asString(product.variation_id),
    asin: asString(product.asin), country: asString(product.country), bought_last_month: asString(product.bought_last_month),
    fabric_details: fabricDetails.map(({ label, value }) => ({ label, value })),
    organic: asBoolean(product.attributes?.is_organic), vegan: asBoolean(product.attributes?.is_vegan),
    vegetarian: asBoolean(product.attributes?.is_vegetarian), dairy_free: asBoolean(product.attributes?.is_dairy_free),
    gluten_free: asBoolean(product.attributes?.is_gluten_free), regional: asBoolean(product.attributes?.is_regional),
    is_new: asBoolean(product.attributes?.is_new),
  });
</script>

<ResultEmbedFullscreen
  appId="shopping" skillId="search_products" skillIconName="search"
  embedHeaderTitle={title} embedHeaderSubtitle={subtitle} result={visibleContext}
  media={productMedia}
  {onClose} currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
>
  {#snippet embedHeaderCta()}{#if product.purchase_url}<EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', product.provider || 'Product')} href={product.purchase_url} />{/if}{/snippet}
  {#snippet summary()}
    <ResultEmbedInfo icon="tag" label={$text('embeds.results_view.price')} value={displayPrice || $text('embeds.shopping.price_unavailable')}>
      <p>{product.base_price || product.grammage || displayPrice || $text('embeds.shopping.price_unavailable')}</p>
      {#if onSale && displayOldPrice}<p>{$text('embeds.shopping.sale')}: <s>{displayOldPrice}</s></p>{/if}
      {#if product.unit}<p>{product.unit}</p>{/if}
    </ResultEmbedInfo>
    {#if product.rating != null}<ResultEmbedInfo icon="star" label={$text('result_embed.rating')} value={ratingText}><p>{ratingText}{#if product.reviews != null} ({product.reviews.toLocaleString()}){/if}</p></ResultEmbedInfo>{/if}
    {#if product.stock != null}<ResultEmbedInfo icon="package" label={$text('embeds.shopping.stock')} value={stockText}><p>{stockText}</p></ResultEmbedInfo>{/if}
  {/snippet}
  {#snippet productMedia()}
      <div class="product-media">
        <div class="product-image-stage">
          {#if imageUrl && !failedImages.includes(activeImage)}
            <img class="product-image" data-testid="shopping-product-image" src={imageUrl} alt={title} loading="lazy" onerror={() => { failedImages = [...failedImages, activeImage]; }} />
          {:else}<div class="image-placeholder" data-testid="shopping-product-placeholder">🛒</div>{/if}
        </div>
        {#if imageUrls.length > 1}
          <div class="gallery-thumbnails" role="group" aria-label={$text('common.images')} data-testid="shopping-product-gallery">
            {#each imageUrls as image, index (image)}<button type="button" class="gallery-thumbnail" class:selected={selectedImage === index} aria-label={`${title} — ${$text('common.images')} ${index + 1} / ${imageUrls.length}`} aria-pressed={selectedImage === index} onclick={() => { selectedImage = index; }} onkeydown={(event) => selectImage(event, index)}><img src={proxyImage(image, 120)} alt="" loading="lazy" /></button>{/each}
          </div>
          <div class="gallery-counter" aria-live="polite" aria-atomic="true">{selectedImage + 1} / {imageUrls.length}</div>
        {/if}
      </div>
  {/snippet}
  {#snippet detailContent()}
    {#if product.brand || product.grammage}<div class="result-location">{[product.brand, product.grammage].filter(Boolean).join(' · ')}</div>{/if}
    <div class="result-icon-row">
      <ResultEmbedInfo icon="package-check" label={$text('embeds.shopping.availability')} state={product.is_salable == null ? 'unknown' : product.is_salable ? 'yes' : 'no'}>
        <p>{product.availability || (product.is_salable == null ? $text('result_embed.availability_unknown') : product.is_salable ? $text('embeds.shopping.available') : $text('embeds.shopping.not_available'))}</p>
        {#if product.stock != null}<p>{$text('embeds.shopping.stock')}: {stockText}</p>{/if}
        {#if colorCount > 0}<p>{$text('embeds.shopping.colors')}: {colorCount}</p>{/if}
      </ResultEmbedInfo>
      {#if product.delivery?.length || product.prime != null}<ResultEmbedInfo icon="truck" label={$text('result_embed.delivery')}>{#each product.delivery || [] as delivery}<p>{delivery}</p>{/each}{#if product.prime != null}<p>Prime: {product.prime ? '✓' : '×'}</p>{/if}</ResultEmbedInfo>{/if}
      {#if product.attributes}<ResultEmbedInfo icon="leaf" label={$text('result_embed.product_attributes')}>
        <dl>{#each Object.entries(product.attributes).filter(([, value]) => value != null && value !== '') as [key, value]}<div><dt>{attributeLabel(key)}</dt><dd>{typeof value === 'boolean' ? value ? '✓' : '×' : String(value)}</dd></div>{/each}</dl>
      </ResultEmbedInfo>{/if}
      {#if product.product_id || product.variation_id || product.category_path || product.bought_last_month || product.asin || product.country}<ResultEmbedInfo icon="info" label={$text('embeds.shopping.product_id')}>
        {#if product.product_id}<p>{$text('embeds.shopping.product_id')}: {product.product_id}</p>{/if}
        {#if product.variation_id}<p>{$text('embeds.shopping.variation_id')}: {product.variation_id}</p>{/if}
        {#if product.asin}<p>ASIN: {product.asin}</p>{/if}
        {#if product.country}<p>{product.country}</p>{/if}
        {#if product.category_path}<p>{product.category_path}</p>{/if}
        {#if product.bought_last_month}<p>{product.bought_last_month}</p>{/if}
      </ResultEmbedInfo>{/if}
    </div>
    {#if fabricDetails.length}<section class="fabric-details"><h3>{$text('embeds.shopping.fabric_details')}</h3><dl>{#each fabricDetails as detail}<div><dt>{detail.label}</dt><dd>{detail.value}</dd></div>{/each}</dl></section>{/if}
  {/snippet}
</ResultEmbedFullscreen>
<style>
  .product-media { width:100%; display:flex; flex-direction:column; align-items:center; }
  .product-image-stage { width:100%; min-height:12rem; display:grid; place-items:center; }
  .product-image { display:block; width:100%; height:auto; max-height:65vh; object-fit:contain; }
  .image-placeholder { font-size:3rem; padding:var(--spacing-12); }
  .gallery-thumbnails { display:flex; gap:var(--spacing-4); max-width:100%; overflow-x:auto; padding:var(--spacing-4); box-sizing:border-box; }
  .gallery-thumbnail { flex:0 0 56px; width:56px; height:56px; padding:var(--spacing-2); border:2px solid transparent; border-radius:var(--radius-3); background:var(--color-grey-0); cursor:pointer; }
  .gallery-thumbnail.selected { border-color:var(--color-button-primary); }
  .gallery-thumbnail:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  .gallery-thumbnail img { width:100%; height:100%; object-fit:contain; }
  .gallery-counter { font-size:var(--font-size-xs); color:var(--color-font-secondary); }
  .fabric-details { width:100%; font-size:var(--font-size-small); }
  h3 { font-size:inherit; }
  dl { margin:0; display:grid; gap:var(--spacing-3); }
  dl > div { display:grid; grid-template-columns:1fr 1fr; gap:var(--spacing-4); }
  dd { margin:0; overflow-wrap:anywhere; }
  dt { color:var(--color-font-secondary); }
</style>
