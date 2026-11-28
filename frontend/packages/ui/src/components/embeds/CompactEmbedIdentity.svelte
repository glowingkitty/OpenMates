<!-- figma-visual-proof: not-required. Reuses the existing preview icon and design tokens. -->
<script lang="ts">
  import EmbedPreviewCorner from '@repo/public-site/components/results/EmbedPreviewCorner.svelte';
  import { resolveIconName } from '../../utils/iconNameResolver';

  let { appId, appIconName, title, subtitle, titleTestId, titleVisible = true, readingTitle = false }: {
    appId: string; appIconName?: string; title: string; subtitle?: string; titleTestId?: string;
    titleVisible?: boolean; readingTitle?: boolean;
  } = $props();
</script>

<div class="identity" data-testid="embed-compact-identity">
  <EmbedPreviewCorner inFlow background={`var(--color-app-${appId}, var(--color-primary))`}
    iconUrl={`var(--icon-url-${resolveIconName(appIconName || appId)}, var(--icon-url-files))`} />
  <div class="text" class:hidden={!titleVisible} aria-hidden={readingTitle || !titleVisible || undefined}
    data-testid="embed-compact-text" data-title-visible={titleVisible} dir="auto">
    <svelte:element this={readingTitle ? 'div' : 'h1'} class="title" data-testid={titleTestId} title={title}>
      <span data-testid="embed-header-title">{title}</span>
    </svelte:element>
    {#if subtitle}<div class="subtitle" title={subtitle} data-testid="embed-header-subtitle">{subtitle}</div>{/if}
  </div>
</div>

<style>
  .identity { display: flex; align-self: stretch; align-items: center; gap: var(--spacing-4); flex: 1; min-width: 0; pointer-events: auto; }
  .text { min-width: 0; flex: 1; }
  .text:not(.hidden) { transition: opacity 160ms ease; }
  .text.hidden { opacity: 0; pointer-events: none; }
  @media (prefers-reduced-motion: reduce) { .text:not(.hidden) { transition: none; } }
  .title, .subtitle { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .title { margin: 0; font-size: var(--font-size-small); font-weight: 700; }
  .subtitle { font-size: var(--font-size-xs); color: var(--color-font-tertiary); }
</style>
