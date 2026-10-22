<!--
  frontend/packages/ui/src/components/embeds/electronics/ElectronicsComponentEmbedPreview.svelte

  Preview card for one Electronics component/reference-design result.
  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
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
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
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
    presentationOnly = false,
    resultContext = 'auto',
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
  resultPreview={true}
  {presentationOnly}
  {resultContext}
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
  {#snippet details()}
    <ResultEmbedCard title={cardTitle} sourceLabel={provider} description={subtitle} textFirst={true}>
      {#snippet facts()}
        {#if efficiency}<ResultEmbedInfo icon="Gauge" label={$text('embeds.electronics.efficiency')} value={efficiency}>{#snippet children()}{efficiency}{/snippet}</ResultEmbedInfo>{/if}
        {#if bomCost}<ResultEmbedInfo icon="Banknote" label={$text('embeds.electronics.bom_cost')} value={bomCost}>{#snippet children()}{bomCost}{#if bom_count != null}<p>{$text('embeds.electronics.bom_count')}: {bom_count}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
        {#if footprint || regulator_type || (bom_count != null && !bomCost)}<ResultEmbedInfo icon="Cpu" label={$text('embeds.electronics.electrical')}>{#snippet children()}{#if footprint}<p>{$text('embeds.electronics.footprint')}: {footprint}</p>{/if}{#if regulator_type}<p>{regulator_type}</p>{/if}{#if bom_count != null}<p>{$text('embeds.electronics.bom_count')}: {bom_count}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
