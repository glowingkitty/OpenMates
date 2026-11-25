<!-- figma-visual-proof: not-required. Reuses the existing preview icon and design tokens. -->
<script lang="ts">
  import EmbedPreviewCorner from '@repo/public-site/components/results/EmbedPreviewCorner.svelte';
  import { resolveIconName } from '../../utils/iconNameResolver';

  let { appId, appIconName, title, subtitle, titleTestId }: {
    appId: string; appIconName?: string; title: string; subtitle?: string; titleTestId?: string;
  } = $props();
</script>

<div class="identity" data-testid="embed-compact-identity">
  <EmbedPreviewCorner compact background={`var(--color-app-${appId}, var(--color-primary))`}
    iconUrl={`var(--icon-url-${resolveIconName(appIconName || appId)}, var(--icon-url-files))`} />
  <div class="text">
    <h1 class="title" data-testid={titleTestId} title={title}>
      <span data-testid="embed-header-title">{title}</span>
    </h1>
    {#if subtitle}<div class="subtitle" title={subtitle} data-testid="embed-header-subtitle">{subtitle}</div>{/if}
  </div>
</div>

<style>
  .identity { display: flex; align-items: center; gap: var(--spacing-4); flex: 1; min-width: 0; pointer-events: auto; }
  .text { min-width: 0; flex: 1; }
  .title, .subtitle { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .title { margin: 0; font-size: var(--font-size-small); font-weight: 700; }
  .subtitle { font-size: var(--font-size-xs); color: var(--color-font-tertiary); }
</style>
