<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryThreadSwatches.svelte

  Row of thread colour swatches in sewing order. The colours are data from the
  design, not theme colours; a thin neutral border keeps white thread visible.
-->
<script lang="ts">
  import type { EmbroideryThread } from './embroideryDesign';

  interface Props {
    threads: EmbroideryThread[];
    /** Swatches shown before collapsing the rest into "+n". */
    max?: number;
  }
  let { threads, max = 8 }: Props = $props();
  const shown = $derived(threads.slice(0, max));
  const hidden = $derived(Math.max(0, threads.length - max));
</script>

{#if threads.length > 0}
  <div class="swatches" data-testid="design-embroidery-swatches" aria-hidden="true">
    {#each shown as thread, index (index)}
      <span class="swatch" data-testid="design-embroidery-swatch" style:background-color={thread.colourHex || undefined}></span>
    {/each}
    {#if hidden > 0}<span class="more">+{hidden}</span>{/if}
  </div>
{/if}

<style>
  .swatches { display: flex; flex-wrap: nowrap; align-items: center; gap: var(--spacing-2); min-width: 0; overflow: hidden; }
  .swatch {
    flex: 0 0 auto;
    width: 0.875rem;
    height: 0.875rem;
    border-radius: 50%;
    border: 1px solid var(--color-grey-40);
    box-sizing: border-box;
  }
  .more { font-size: var(--font-size-xxs); color: var(--color-font-secondary); }
</style>
