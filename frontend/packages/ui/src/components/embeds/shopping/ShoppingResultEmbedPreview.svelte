<!--
  frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedPreview.svelte

  Preview card for a single shopping product result.
  Uses UnifiedEmbedPreview as the base card and mirrors the child-card pattern
  used by other search fullscreens (images/travel/events/web).

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from "../../../types/authoredResult";
  import { getContext } from "svelte";
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

  const MAX_WIDTH_PREVIEW_IMAGE = 480;
  const MAX_WIDTH_LARGE_PREVIEW_IMAGE = 960;

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

  interface Props {
    id: string;
    title?: string;
    brand?: string;
    price_cents?: number | null;
    price_eur?: string | null;
    base_price?: string | null;
    stock?: number | null;
    availability?: string | null;
    color_child_item_ids?: string[];
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
    resultContext?: 'auto' | 'chat' | 'results';
    variant?: 'small' | 'large';
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    brand,
    price_cents = null,
    price_eur = null,
    base_price = null,
    was_price_cents = null,
    grammage = null,
    image_url = null,
    old_price = null,
    old_price_amount = null,
    price = null,
    price_amount = null,
    currency_symbol = null,
    rating = null,
    reviews = null,
    status = 'finished',
    isMobile = false,
    resultContext = 'auto',
    variant = 'small',
    onFullscreen,
  }: Props = $props();
  const authoredContext = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);
  let isAuthored = $derived(Boolean(authoredContext?.authoring));

  let authoredCurrency = $derived(typeof authoredContext?.content?.currency === 'string' ? String(authoredContext?.content?.currency) : '');
  function formatCents(value: number | null | undefined): string {
    if (value == null || value < 0) return '';
    return isAuthored ? `${(value / 100).toFixed(2)} ${authoredCurrency}`.trim() : `${(value / 100).toFixed(2).replace('.', ',')} €`;
  }

  function formatAmount(value: number | null | undefined, symbol?: string | null): string {
    if (value == null || value < 0) return '';
    const currency = symbol || (isAuthored ? authoredCurrency : '€');
    const amount = currency === '€' ? value.toFixed(2).replace('.', ',') : value.toFixed(2);
    return isAuthored && /^[A-Za-z]{3}$/.test(currency) ? `${currency} ${amount}` : `${currency}${amount}`;
  }

  function getDisplayPrice(): string {
    if (isAuthored && typeof authoredContext?.content.price === 'number') return formatAmount(authoredContext.content.price, currency_symbol);
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

  let cardTitle = $derived(title || brand || 'Product');
  let displayPrice = $derived(getDisplayPrice());
  let displayOldPrice = $derived(getDisplayOldPrice());
  let onSale = $derived(hasSale());
  let imageProxyWidth = $derived(variant === 'large' ? MAX_WIDTH_LARGE_PREVIEW_IMAGE : MAX_WIDTH_PREVIEW_IMAGE);
  let imageUrl = $derived(image_url ? proxyImage(image_url, imageProxyWidth) : '');

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
  {resultContext}
  resultPreview={true}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <ResultEmbedCard title={cardTitle} description={[brand, grammage, base_price].filter(Boolean).join(' · ')} imageUrl={imageUrl} imageAlt={cardTitle} mediaFit="contain">
      {#snippet facts()}<span class="result-price">{displayPrice || $text('embeds.shopping.price_unavailable')}</span>{#if onSale && displayOldPrice}<s>{displayOldPrice}</s>{/if}{#if rating != null}<span>★ {rating.toFixed(1)}{#if reviews != null} ({reviews.toLocaleString()}){/if}</span>{/if}{/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
