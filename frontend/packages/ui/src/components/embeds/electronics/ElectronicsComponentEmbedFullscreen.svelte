<!--
  frontend/packages/ui/src/components/embeds/electronics/ElectronicsComponentEmbedFullscreen.svelte

  Fullscreen detail view for a single electronics component/reference design.
  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

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
    component?: ElectronicsComponentResult;
    data?: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    component,
    data,
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

  function asNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  }

  function asBoolean(value: unknown): boolean | null {
    if (typeof value === 'boolean') return value;
    if (value === 'true' || value === '1' || value === 1) return true;
    if (value === 'false' || value === '0' || value === 0) return false;
    return null;
  }

  function componentFromData(
    rawData: EmbedFullscreenRawData | undefined,
    fallbackEmbedId: string | undefined,
  ): ElectronicsComponentResult {
    const content = rawData?.decodedContent ?? {};
    const embedData = rawData?.embedData ?? {};
    const attrs = rawData?.attrs ?? {};

    return {
      embed_id:
        asString(content.embed_id) ||
        asString(embedData.embed_id) ||
        asString(attrs.id) ||
        fallbackEmbedId ||
        'electronics-component',
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
      bom_cost_usd: asNumber(content.bom_cost_usd),
      bom_count: asNumber(content.bom_count),
      efficiency_percent: asNumber(content.efficiency_percent),
      footprint_mm2: asNumber(content.footprint_mm2),
      frequency_hz: asNumber(content.frequency_hz),
      max_output_current_a: asNumber(content.max_output_current_a),
      output_ripple_vpp: asNumber(content.output_ripple_vpp),
      input_voltage_min_v: asNumber(content.input_voltage_min_v),
      input_voltage_max_v: asNumber(content.input_voltage_max_v),
      output_voltage_min_v: asNumber(content.output_voltage_min_v),
      output_voltage_max_v: asNumber(content.output_voltage_max_v),
      isolated: asBoolean(content.isolated),
    };
  }

  function formatNumber(value: number | null | undefined, suffix = ''): string {
    if (value == null || !Number.isFinite(value)) return '';
    return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
  }

  function detail(label: string, value: string | null | undefined): { label: string; value: string } | null {
    if (!value) return null;
    return { label, value };
  }

  let componentData = $derived(component ?? componentFromData(data, embedId));
  let title = $derived(componentData.part_number || componentData.base_part_number || componentData.title || 'Component');
  let subtitle = $derived([componentData.topology, componentData.package, componentData.provider || 'TI WEBENCH'].filter(Boolean).join(' / '));
  let performanceDetails = $derived([
    detail($text('embeds.electronics.efficiency'), formatNumber(componentData.efficiency_percent, '%')),
    detail($text('embeds.electronics.bom_cost'), formatNumber(componentData.bom_cost_usd, ' USD')),
    detail($text('embeds.electronics.bom_count'), componentData.bom_count == null ? '' : String(componentData.bom_count)),
    detail($text('embeds.electronics.footprint'), formatNumber(componentData.footprint_mm2, ' mm2')),
    detail($text('embeds.electronics.frequency'), formatNumber(componentData.frequency_hz, ' Hz')),
    detail($text('embeds.electronics.output_current'), formatNumber(componentData.max_output_current_a, ' A')),
    detail($text('embeds.electronics.output_ripple'), formatNumber(componentData.output_ripple_vpp, ' Vpp')),
  ].filter((item): item is { label: string; value: string } => item != null));

  let electricalDetails = $derived([
    detail(
      $text('embeds.electronics.input_voltage'),
      `${formatNumber(componentData.input_voltage_min_v, ' V')} - ${formatNumber(componentData.input_voltage_max_v, ' V')}`.trim(),
    ),
    detail(
      $text('embeds.electronics.output_voltage'),
      `${formatNumber(componentData.output_voltage_min_v, ' V')} - ${formatNumber(componentData.output_voltage_max_v, ' V')}`.trim(),
    ),
    detail($text('embeds.electronics.topology'), componentData.topology || ''),
    detail($text('embeds.electronics.regulator_type'), componentData.regulator_type || ''),
    detail($text('embeds.electronics.control_mode'), componentData.control_mode || ''),
    detail(
      $text('embeds.electronics.isolated'),
      componentData.isolated == null ? '' : (componentData.isolated ? $text('embeds.electronics.yes') : $text('embeds.electronics.no')),
    ),
  ].filter((item): item is { label: string; value: string } => item != null && item.value !== ' -'));
</script>

<UnifiedEmbedFullscreen
  appId="electronics"
  skillId="search_components"
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
    {#if componentData.product_url}
      <EmbedHeaderCtaButton
        label={$text('embeds.open_on_provider').replace('{provider}', componentData.provider || 'TI')}
        href={componentData.product_url}
      />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="component-fullscreen">
      <section class="hero-card">
        <div class="eyebrow">{componentData.provider || 'TI WEBENCH'}</div>
        <h2>{title}</h2>
        {#if componentData.description}
          <p>{componentData.description}</p>
        {/if}
        <div class="link-row">
          {#if componentData.product_url}
            <a href={componentData.product_url} target="_blank" rel="noopener noreferrer">{$text('embeds.electronics.product_page')}</a>
          {/if}
          {#if componentData.datasheet_url}
            <a href={componentData.datasheet_url} target="_blank" rel="noopener noreferrer">{$text('embeds.electronics.datasheet')}</a>
          {/if}
        </div>
      </section>

      <section class="details-section">
        <h3>{$text('embeds.electronics.performance')}</h3>
        <div class="detail-grid">
          {#each performanceDetails as item}
            <div class="detail-item">
              <span class="detail-label">{item.label}</span>
              <span class="detail-value">{item.value}</span>
            </div>
          {/each}
        </div>
      </section>

      <section class="details-section">
        <h3>{$text('embeds.electronics.electrical')}</h3>
        <div class="detail-grid">
          {#each electricalDetails as item}
            <div class="detail-item">
              <span class="detail-label">{item.label}</span>
              <span class="detail-value">{item.value}</span>
            </div>
          {/each}
        </div>
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .component-fullscreen {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: min(100%, 1000px);
    margin: 0 auto;
    padding: var(--spacing-6);
  }

  .hero-card,
  .details-section {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-6);
    background: var(--color-grey-0);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  }

  .hero-card {
    padding: var(--spacing-7);
  }

  .eyebrow {
    color: var(--color-primary);
    font-size: var(--font-size-xs);
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    margin-top: var(--spacing-2);
    color: var(--color-font-primary);
    font-size: var(--font-size-h2);
    line-height: 1.15;
  }

  p {
    margin-top: var(--spacing-4);
    color: var(--color-grey-70);
    line-height: 1.55;
  }

  .link-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    margin-top: var(--spacing-5);
  }

  .link-row a {
    color: var(--color-primary);
    font-weight: 700;
    text-decoration: none;
  }

  .details-section {
    padding: var(--spacing-6);
  }

  h3 {
    color: var(--color-font-primary);
    font-size: var(--font-size-h3);
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--spacing-3);
    margin-top: var(--spacing-4);
  }

  .detail-item {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-1);
    padding: var(--spacing-3);
    border-radius: var(--radius-4);
    background: var(--color-grey-5);
  }

  .detail-label {
    color: var(--color-grey-60);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  .detail-value {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
  }
</style>
