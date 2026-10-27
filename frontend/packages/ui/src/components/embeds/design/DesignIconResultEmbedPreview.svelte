<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconResultEmbedPreview.svelte

  Preview card for a single free SVG icon result from the Design app.
  Kept deliberately small so direct child embeds can render in chat groups,
  saved embeds, and fullscreen result grids without custom layout branches.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { getApiEndpoint } from '../../../config/api';

  interface Props {
    id: string;
    icon_id?: string;
    prefix?: string;
    name?: string;
    display_name?: string;
    collection_name?: string;
    license_title?: string;
    svg_path?: string;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    icon_id,
    prefix,
    name,
    display_name,
    collection_name,
    license_title,
    svg_path,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let iconLabel = $derived(display_name || name || icon_id || 'Icon');
  let iconMeta = $derived(collection_name || prefix || license_title || 'SVG icon');
  let iconSrc = $derived(svg_path ? getApiEndpoint(svg_path) : '');

  function handleStop() {
    // Icon results are already resolved server-side.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="design"
  skillId="search_icons"
  skillIconName="search"
  {status}
  skillName={iconLabel}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  resultPreview={true}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <ResultEmbedCard title={iconLabel} description={iconMeta} sourceLabel={license_title} imageUrl={iconSrc} imageAlt={iconLabel} mediaFit="contain" />
  {/snippet}
</UnifiedEmbedPreview>
