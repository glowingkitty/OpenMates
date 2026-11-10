<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryThreadList.svelte

  Thread list in sewing order: number, colour swatch, name and stitch count.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { formatCount, type EmbroideryThread } from './embroideryDesign';

  interface Props { threads: EmbroideryThread[]; }
  let { threads }: Props = $props();
</script>

{#if threads.length > 0}
  <section class="threads" data-testid="design-embroidery-threads">
    <h4>{$text('embeds.design.embroidery.threads')}</h4>
    <ol>
      {#each threads as thread, index (index)}
        <li data-testid="design-embroidery-thread">
          <span class="number">{index + 1}</span>
          <span class="swatch" style:background-color={thread.colourHex || undefined}></span>
          <span class="name">{thread.name}</span>
          <span class="count">{formatCount(thread.stitchCount)} {$text('embeds.design.embroidery.stitches_unit')}</span>
        </li>
      {/each}
    </ol>
  </section>
{/if}

<style>
  .threads { width: 100%; }
  h4 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-2); }
  li {
    display: grid;
    grid-template-columns: 1.5rem 1.25rem minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--spacing-4);
    padding: var(--spacing-3) var(--spacing-5);
    background: var(--color-grey-0);
    border-radius: var(--radius-4);
    font-size: var(--font-size-small);
  }
  .number { color: var(--color-font-secondary); text-align: end; font-variant-numeric: tabular-nums; }
  .swatch { width: 1.25rem; height: 1.25rem; border-radius: 50%; border: 1px solid var(--color-grey-40); box-sizing: border-box; }
  .name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-font-primary); }
  .count { color: var(--color-font-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
