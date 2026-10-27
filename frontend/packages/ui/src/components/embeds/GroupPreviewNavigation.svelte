<script lang="ts">
  import EmbedChevron from './EmbedChevron.svelte';
  let { onPrevious, onNext }: { onPrevious: () => void; onNext: () => void } = $props();
</script>

<div class="group-preview-navigation" data-testid="grouped-preview-navigation">
  <button type="button" aria-label="Previous" data-testid="grouped-preview-previous" onclick={(event) => { event.stopPropagation(); onPrevious(); }}><EmbedChevron direction="previous" /></button>
  <button type="button" aria-label="Next" data-testid="grouped-preview-next" onclick={(event) => { event.stopPropagation(); onNext(); }}><EmbedChevron direction="next" /></button>
</div>

<style>
  .group-preview-navigation { position:absolute; inset:0; pointer-events:none; z-index:5; }
  button { all:unset; box-sizing:border-box; position:absolute; bottom:10px; min-width:0; min-height:0; width:36px; height:36px; margin:0; padding:0; border:0; border-radius:50%; display:grid; place-items:center; color:var(--color-font-primary); background:var(--color-grey-0); box-shadow:0 2px 8px #0002; pointer-events:auto; cursor:pointer; }
  button:first-child { left:10px; }
  button:last-child { right:10px; }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
</style>
