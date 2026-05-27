<!--
  frontend/packages/ui/src/components/embeds/electronics/ElectronicsComponentEmbedPreview.svelte

  Preview card for one Electronics component/reference-design result.
  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface Props {
    id: string;
    title?: string;
    part_number?: string;
    base_part_number?: string;
    provider?: string;
    topology?: string | null;
    package?: string | null;
    regulator_type?: string | null;
    bom_cost_usd?: number | null;
    bom_count?: number | null;
    efficiency_percent?: number | null;
    footprint_mm2?: number | null;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    part_number,
    base_part_number,
    provider = 'TI WEBENCH',
    topology = null,
    package: packageName = null,
    regulator_type = null,
    bom_cost_usd = null,
    bom_count = null,
    efficiency_percent = null,
    footprint_mm2 = null,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  function formatNumber(value: number | null | undefined, suffix = ''): string {
    if (value == null || !Number.isFinite(value)) return '';
    return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
  }

  let cardTitle = $derived(part_number || base_part_number || title || 'Component');
  let subtitle = $derived([topology, packageName].filter(Boolean).join(' / '));
  let efficiency = $derived(formatNumber(efficiency_percent, '%'));
  let bomCost = $derived(formatNumber(bom_cost_usd, ' USD'));
  let footprint = $derived(formatNumber(footprint_mm2, ' mm2'));

  function handleStop() {
    // Component cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="electronics"
  skillId="search_components"
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
    <div class="component-preview" class:mobile={isMobileLayout}>
      <div class="component-title">{cardTitle}</div>
      {#if subtitle}
        <div class="component-subtitle">{subtitle}</div>
      {/if}

      <div class="metric-grid">
        {#if efficiency}
          <div class="metric">
            <span class="metric-label">{$text('embeds.electronics.efficiency')}</span>
            <span class="metric-value">{efficiency}</span>
          </div>
        {/if}
        {#if bomCost}
          <div class="metric">
            <span class="metric-label">{$text('embeds.electronics.bom_cost')}</span>
            <span class="metric-value">{bomCost}</span>
          </div>
        {/if}
        {#if footprint}
          <div class="metric">
            <span class="metric-label">{$text('embeds.electronics.footprint')}</span>
            <span class="metric-value">{footprint}</span>
          </div>
        {/if}
        {#if bom_count != null}
          <div class="metric">
            <span class="metric-label">{$text('embeds.electronics.bom_count')}</span>
            <span class="metric-value">{bom_count}</span>
          </div>
        {/if}
      </div>

      <div class="provider-row">
        {#if regulator_type}<span>{regulator_type}</span>{/if}
        <span>{provider}</span>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .component-preview {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-2);
    height: 100%;
    width: 100%;
  }

  .component-preview.mobile {
    justify-content: flex-start;
  }

  .component-title {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
    line-height: 1.25;
  }

  .component-subtitle,
  .provider-row {
    color: var(--color-grey-70);
    font-size: var(--font-size-xxs);
    line-height: 1.3;
  }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--spacing-2);
    margin-top: var(--spacing-1);
  }

  .metric {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: var(--spacing-2);
    border-radius: var(--radius-3);
    background: var(--color-grey-5);
  }

  .metric-label {
    color: var(--color-grey-60);
    font-size: var(--font-size-micro);
    font-weight: 600;
    text-transform: uppercase;
  }

  .metric-value {
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
    font-weight: 700;
  }

  .provider-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
  }
</style>
