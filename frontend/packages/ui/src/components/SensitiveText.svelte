<!--
  Render plain embed text with accessible sensitive-data toggles.
  Only values with available mappings become interactive; originals are never
  added to hidden-mode markup. The parent owns visibility and synchronization.
  Wiki links retain the existing escaped rendering and hydration path.
  Used by mail previews and fullscreen fields outside the message editor.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { PIIMapping } from '../types/chat';
  import { hydrateWikiLinks, replaceWikiLinksInText } from '../utils/embedLinkUtils';

  let { value, mappings, revealed, onToggle }: {
    value: string;
    mappings: PIIMapping[];
    revealed: boolean;
    onToggle?: () => void;
  } = $props();
  let root: HTMLSpanElement;
  const pieces = $derived.by(() => {
    const values = [...new Set(mappings.map(mapping => revealed ? mapping.original : mapping.placeholder))]
      .filter(Boolean).sort((a, b) => b.length - a.length);
    const result: { value: string; sensitive: boolean }[] = [];
    let offset = 0;
    while (offset < value.length) {
      let next = value.length;
      let match = '';
      for (const candidate of values) {
        const index = value.indexOf(candidate, offset);
        if (index >= 0 && index < next) { next = index; match = candidate; }
      }
      if (next > offset) result.push({ value: value.slice(offset, next), sensitive: false });
      if (!match) break;
      result.push({ value: match, sensitive: true });
      offset = next + match.length;
    }
    return result;
  });
  $effect(() => {
    void pieces;
    if (root) return hydrateWikiLinks(root);
  });
</script>

<span bind:this={root}>
  {#each pieces as piece}
    {#if piece.sensitive && onToggle}
      <button type="button" class="sensitive-text" class:revealed
        aria-label={$text(revealed ? 'chat.pii_hide' : 'chat.pii_show')}
        onclick={(event) => { event.stopPropagation(); onToggle?.(); }}
      >{piece.value}</button>
    {:else}
      {@const html = replaceWikiLinksInText(piece.value)}
      {#if html}
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- Escaped by replaceWikiLinksInText. -->
        {@html html}
      {:else}{piece.value}{/if}
    {/if}
  {/each}
</span>

<style>
  .sensitive-text {
    all: unset;
    display: inline;
    color: #4ade80;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    overflow-wrap: anywhere;
  }
  .sensitive-text.revealed { color: #f59e0b; }
  .sensitive-text:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
</style>
