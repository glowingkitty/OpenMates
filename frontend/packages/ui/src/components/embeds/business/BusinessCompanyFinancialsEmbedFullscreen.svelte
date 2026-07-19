<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialsEmbedFullscreen.svelte

  Fullscreen grid for Business / Get company financials parent embeds. It loads
  one child company financial result card per resolved public company.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import BusinessCompanyFinancialResultEmbedPreview from './BusinessCompanyFinancialResultEmbedPreview.svelte';
  import BusinessCompanyFinancialResultEmbedFullscreen from './BusinessCompanyFinancialResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  interface FinancialResult {
    embed_id: string;
    company?: string;
    ticker?: string;
    fiscal_year?: number | null;
    fiscal_quarter?: string | null;
    period_type?: string;
    currency?: string;
    revenue?: number | null;
    net_income?: number | null;
    filed?: string;
    form?: string;
    source_url?: string;
    accession_number?: string;
    [key: string]: unknown;
  }

  interface Props {
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

  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : $text('app_skills.business.company_financials'));
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'SEC EDGAR');
  let period = $derived(typeof data.decodedContent?.period === 'string' ? data.decodedContent.period.replace(/_/g, ' ') : 'latest annual');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let legacyResults = $derived(extractSearchResultsFromContent(data.decodedContent, ['results', 'preview_results']));

  function transformToFinancialResult(childEmbedId: string, content: Record<string, unknown>): FinancialResult {
    return { embed_id: childEmbedId, ...content } as FinancialResult;
  }

  function transformLegacyResults(results: unknown[]): FinancialResult[] {
    return (results as Array<Record<string, unknown>>).map((result, index) => transformToFinancialResult(`legacy-company-financial-${index}`, result));
  }
</script>

<SearchResultsTemplate
  appId="business"
  skillId="company_financials"
  skillIconName="business"
  embedHeaderTitle={query}
  embedHeaderSubtitle={`${period} · ${$text('embeds.via')} ${provider}`}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToFinancialResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  skeletonCount={4}
  minCardWidth="260px"
>
  {#snippet resultCard({ result, onSelect })}
    <BusinessCompanyFinancialResultEmbedPreview
      id={result.embed_id}
      company={result.company}
      ticker={result.ticker}
      fiscalYear={result.fiscal_year}
      fiscalQuarter={result.fiscal_quarter}
      periodType={result.period_type}
      currency={result.currency}
      revenue={result.revenue}
      netIncome={result.net_income}
      filed={result.filed}
      form={result.form}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <BusinessCompanyFinancialResultEmbedFullscreen
      data={{ decodedContent: nav.result }}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
      onClose={nav.onClose}
    />
  {/snippet}
</SearchResultsTemplate>
