<!--
  frontend/packages/ui/src/components/embeds/electronics/ElectronicsSearchEmbedFullscreen.svelte

  Fullscreen view for Electronics component search results.
  Uses SearchResultsTemplate for child embed loading and drill-down.
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import ElectronicsComponentEmbedPreview from './ElectronicsComponentEmbedPreview.svelte';
  import ElectronicsComponentEmbedFullscreen from './ElectronicsComponentEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  interface ElectronicsComponentResult {
    embed_id: string;
    title?: string;
    part_number?: string;
    base_part_number?: string;
    provider?: string;
    topology?: string | null;
    package?: string | null;
    regulator_type?: string | null;
    control_mode?: string | null;
    product_url?: string;
    datasheet_url?: string;
    description?: string | null;
    bom_cost_usd?: number | null;
    bom_count?: number | null;
    efficiency_percent?: number | null;
    footprint_mm2?: number | null;
    frequency_hz?: number | null;
    max_output_current_a?: number | null;
    output_ripple_vpp?: number | null;
    input_voltage_min_v?: number | null;
    input_voltage_max_v?: number | null;
    output_voltage_min_v?: number | null;
    output_voltage_max_v?: number | null;
    isolated?: boolean | null;
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

  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  let localQuery = $state('Power converters');
  let localProvider = $state('TI WEBENCH');
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let storeResolved = $state(false);

  $effect(() => {
    if (!storeResolved) {
      localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Power converters';
      localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'TI WEBENCH';
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

  function transformToComponentResult(embedId: string, content: Record<string, unknown>): ElectronicsComponentResult {
    return {
      embed_id: asString(content.embed_id) || embedId,
      title: asString(content.title),
      part_number: asString(content.part_number),
      base_part_number: asString(content.base_part_number),
      provider: asString(content.provider) || 'TI WEBENCH',
      topology: asString(content.topology) || null,
      package: asString(content.package) || null,
      regulator_type: asString(content.regulator_type) || null,
      control_mode: asString(content.control_mode) || null,
      product_url: asString(content.product_url),
      datasheet_url: asString(content.datasheet_url),
      description: asString(content.description) || null,
      bom_cost_usd: asNumber(content.bom_cost_usd) ?? null,
      bom_count: asNumber(content.bom_count) ?? null,
      efficiency_percent: asNumber(content.efficiency_percent) ?? null,
      footprint_mm2: asNumber(content.footprint_mm2) ?? null,
      frequency_hz: asNumber(content.frequency_hz) ?? null,
      max_output_current_a: asNumber(content.max_output_current_a) ?? null,
      output_ripple_vpp: asNumber(content.output_ripple_vpp) ?? null,
      input_voltage_min_v: asNumber(content.input_voltage_min_v) ?? null,
      input_voltage_max_v: asNumber(content.input_voltage_max_v) ?? null,
      output_voltage_min_v: asNumber(content.output_voltage_min_v) ?? null,
      output_voltage_max_v: asNumber(content.output_voltage_max_v) ?? null,
      isolated: asBoolean(content.isolated) ?? null,
    };
  }

  function transformLegacyResults(results: unknown[]): ElectronicsComponentResult[] {
    const transformed: ElectronicsComponentResult[] = [];
    for (let i = 0; i < results.length; i++) {
      const item = results[i] as Record<string, unknown>;
      if (!item || typeof item !== 'object') continue;
      if (Array.isArray(item.results)) {
        for (let j = 0; j < item.results.length; j++) {
          const child = item.results[j] as Record<string, unknown>;
          if (child && typeof child === 'object') transformed.push(transformToComponentResult(`legacy-${i}-${j}`, child));
        }
      } else {
        transformed.push(transformToComponentResult(`legacy-${i}`, item));
      }
    }
    return transformed;
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') storeResolved = true;

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results;
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  let headerTitle = $derived(query || $text('common.search'));
  let headerSubtitle = $derived(`${$text('embeds.via')} ${provider}`);
</script>

<SearchResultsTemplate
  appId="electronics"
  skillId="search_components"
  maxGridWidth="1100px"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToComponentResult}
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
    <ElectronicsComponentEmbedPreview
      id={result.embed_id}
      title={result.title}
      part_number={result.part_number}
      base_part_number={result.base_part_number}
      provider={result.provider}
      topology={result.topology}
      package={result.package}
      regulator_type={result.regulator_type}
      bom_cost_usd={result.bom_cost_usd}
      bom_count={result.bom_count}
      efficiency_percent={result.efficiency_percent}
      footprint_mm2={result.footprint_mm2}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <ElectronicsComponentEmbedFullscreen
      component={nav.result}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
