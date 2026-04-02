<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingSearchEmbedFullscreen.svelte

  Fullscreen view for the Shopping Search Products skill embed.
  Uses SearchResultsTemplate for unified search grid + child fullscreen overlay.
  Renders ShoppingResultEmbedPreview cards and drills into ShoppingResultEmbedFullscreen.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import ShoppingResultEmbedPreview from './ShoppingResultEmbedPreview.svelte';
  import ShoppingResultEmbedFullscreen from './ShoppingResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  interface ProductAttributes {
    is_organic?: boolean;
    is_vegan?: boolean;
    is_vegetarian?: boolean;
    is_dairy_free?: boolean;
    is_gluten_free?: boolean;
    is_new?: boolean;
    is_regional?: boolean;
    is_lowest_price?: boolean;
  }

  interface ShoppingResult {
    embed_id: string;
    product_id?: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;
    was_price_cents?: number | null;
    grammage?: string | null;
    purchase_url?: string;
    image_url?: string | null;
    category_path?: string | null;
    total_result_count?: number;
    search_rank?: number;
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
    amazon_domain?: string;
    attributes?: ProductAttributes;
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // Extract fields from data prop
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  let localQuery = $state('');
  let localProvider = $state('REWE');
  // embedIdsOverride: only set by handleEmbedDataUpdated during streaming;
  // falls back to the raw embedIds prop so it's available at mount time.
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let storeResolved = $state(false);
  let localErrorMessage = $state('');

  $effect(() => {
    if (!storeResolved) {
      localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
      localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'REWE';
      localResults = Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : [];
      localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
      localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error as string : '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let legacyResults = $derived(localResults);

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
      is_organic: asBoolean(attrs.is_organic),
      is_vegan: asBoolean(attrs.is_vegan),
      is_vegetarian: asBoolean(attrs.is_vegetarian),
      is_dairy_free: asBoolean(attrs.is_dairy_free),
      is_gluten_free: asBoolean(attrs.is_gluten_free),
      is_new: asBoolean(attrs.is_new),
      is_regional: asBoolean(attrs.is_regional),
      is_lowest_price: asBoolean(attrs.is_lowest_price),
    };
  }

  function transformToShoppingResult(embedId: string, content: Record<string, unknown>): ShoppingResult {
    return {
      embed_id: asString(content.embed_id) || embedId,
      product_id: asString(content.product_id),
      title: asString(content.title),
      brand: asString(content.brand),
      price_cents: asNumber(content.price_cents) ?? null,
      price_eur: asString(content.price_eur) || null,
      was_price_cents: asNumber(content.was_price_cents) ?? null,
      grammage: asString(content.grammage) || null,
      purchase_url: asString(content.purchase_url) || asString(content.url),
      image_url: asString(content.image_url) || null,
      category_path: asString(content.category_path) || null,
      total_result_count: asNumber(content.total_result_count),
      search_rank: asNumber(content.search_rank),
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
      amazon_domain: asString(content.amazon_domain),
      attributes: parseAttributes(content),
    };
  }

  function transformLegacyResults(results: unknown[]): ShoppingResult[] {
    const transformed: ShoppingResult[] = [];

    for (let i = 0; i < results.length; i++) {
      const item = results[i] as Record<string, unknown>;
      if (!item || typeof item !== 'object') continue;

      const groupedResults = item.results;
      if (Array.isArray(groupedResults)) {
        for (let j = 0; j < groupedResults.length; j++) {
          const groupedItem = groupedResults[j] as Record<string, unknown>;
          if (!groupedItem || typeof groupedItem !== 'object') continue;
          transformed.push(transformToShoppingResult(`legacy-${i}-${j}`, groupedItem));
        }
        continue;
      }

      transformed.push(transformToShoppingResult(`legacy-${i}`, item));
    }

    return transformed;
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;

    if (
      data.status === 'processing' ||
      data.status === 'finished' ||
      data.status === 'error' ||
      data.status === 'cancelled'
    ) {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results;
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  let providerLabel = $derived.by(() => {
    const normalized = provider.trim().toUpperCase();
    if (normalized === 'AMAZON') {
      return provider;
    }
    if (normalized === 'REWE') return 'REWE';
    return provider;
  });

  let headerTitle = $derived(query || $text('common.search'));
  let headerSubtitle = $derived(`${$text('embeds.via')} ${providerLabel}`);
</script>

<SearchResultsTemplate
  appId="shopping"
  skillId="search_products"
  minCardWidth="220px"
  maxGridWidth="1100px"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToShoppingResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage || $text('chat.an_error_occured')}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <ShoppingResultEmbedPreview
      id={result.embed_id}
      title={result.title}
      brand={result.brand}
      price_cents={result.price_cents}
      price_eur={result.price_eur}
      was_price_cents={result.was_price_cents}
      grammage={result.grammage}
      image_url={result.image_url}
      old_price={result.old_price}
      old_price_amount={result.old_price_amount}
      price={result.price}
      price_amount={result.price_amount}
      currency_symbol={result.currency_symbol}
      attributes={result.attributes}
      rating={result.rating}
      reviews={result.reviews}
      prime={result.prime}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <ShoppingResultEmbedFullscreen
      product={nav.result}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon='search']) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
