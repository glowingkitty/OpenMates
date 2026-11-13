<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryThreadList.svelte

  Thread list in sewing order: number, colour swatch, name, rough thread length
  and sewing minutes (stitch count for results stored without them), with a
  remark that these are estimates.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { formatCount, formatDuration, formatThreadLength, type EmbroideryThread } from './embroideryDesign';

  interface Props { threads: EmbroideryThread[]; }
  let { threads }: Props = $props();
  const showMinutes = $derived(threads.some((thread) => thread.estimatedMinutes !== null));
</script>

{#if threads.length > 0}
  <section class="threads" class:with-minutes={showMinutes} data-testid="design-embroidery-threads">
    <h4>{$text('embeds.design.embroidery.threads')}</h4>
    <ol>
      {#each threads as thread, index (index)}
        <li data-testid="design-embroidery-thread">
          <span class="number">{index + 1}</span>
          <span class="swatch" style:background-color={thread.colourHex || undefined}></span>
          <span class="name">{thread.name}</span>
          {#if thread.threadLengthM !== null}
            <span class="count" data-testid="design-embroidery-thread-length-row">~{formatThreadLength(thread.threadLengthM)}</span>
          {:else}
            <span class="count">{formatCount(thread.stitchCount)} {$text('embeds.design.embroidery.stitches_unit')}</span>
          {/if}
          {#if showMinutes}
            <span class="minutes" data-testid="design-embroidery-thread-minutes">{thread.estimatedMinutes === null ? '' : `~${formatDuration(thread.estimatedMinutes)}`}</span>
          {/if}
        </li>
      {/each}
    </ol>
    {#if showMinutes}
    <p class="estimate-note" data-testid="design-embroidery-time-note">{$text('embeds.design.embroidery.sewing_time_note')}</p>
    {/if}
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
  .with-minutes li { grid-template-columns: 1.5rem 1.25rem minmax(0, 1fr) auto 4.5rem; }
  .count { color: var(--color-font-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .minutes { color: var(--color-font-primary); font-variant-numeric: tabular-nums; white-space: nowrap; text-align: end; }
  .estimate-note { margin: var(--spacing-4) 0 0; font-size: var(--font-size-xs); color: var(--color-font-secondary); }
</style>
