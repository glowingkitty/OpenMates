<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconResultEmbedPreview.svelte

  Preview card for a single free SVG icon result from the Design app.
  Kept deliberately small so direct child embeds can render in chat groups,
  saved embeds, and fullscreen result grids without custom layout branches.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
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
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="icon-result-preview" class:mobile={isMobileLayout}>
      <div class="icon-art" aria-hidden="true">
        {#if iconSrc}
          <img src={iconSrc} alt="" loading="lazy" />
        {:else}
          <span class="clickable-icon icon_design placeholder-icon"></span>
        {/if}
      </div>
      <div class="icon-copy">
        <div class="icon-title">{iconLabel}</div>
        <div class="icon-meta">{iconMeta}</div>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .icon-result-preview {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    height: 100%;
    width: 100%;
  }

  .icon-result-preview.mobile {
    align-items: flex-start;
  }

  .icon-art {
    display: grid;
    place-items: center;
    flex: 0 0 58px;
    width: 58px;
    height: 58px;
    border-radius: var(--radius-4);
    background: var(--color-grey-8);
    border: 1px solid var(--color-grey-20);
  }

  .icon-art img {
    width: 32px;
    height: 32px;
    object-fit: contain;
  }

  .placeholder-icon {
    width: 26px;
    height: 26px;
    background: var(--color-grey-50) !important;
  }

  .icon-copy {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-1);
    min-width: 0;
  }

  .icon-title {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .icon-meta {
    color: var(--color-grey-70);
    font-size: var(--font-size-xxs);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
