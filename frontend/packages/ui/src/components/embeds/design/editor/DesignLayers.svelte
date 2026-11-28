<!-- figma-visual-proof: not-required. Original OpenMates preview with browser proof. -->
<script lang="ts">
  import EmbedIconButton from '../../shared/EmbedIconButton.svelte';
  import type { DesignLayer } from './designDocument';

  interface Props {
    layers: DesignLayer[];
    selectedId: string | null;
    onSelect: (id: string) => void;
    onChange: (layer: DesignLayer) => void;
    onOrder: (direction: number) => void;
    onClose: () => void;
  }

  let { layers, selectedId, onSelect, onChange, onOrder, onClose }: Props = $props();
  const batch = 40;
  let start = $state(0);
  const selectedIndex = $derived(layers.findIndex((layer) => layer.id === selectedId));
  const names = { text: 'text', shape: 'element', path: 'diagram', image: 'image' };
  let lastSelection: string | null = null;

  $effect(() => {
    if (selectedIndex >= 0 && selectedId !== lastSelection) {
      start = Math.floor((layers.length - 1 - selectedIndex) / batch) * batch;
    } else if (start >= layers.length && start > 0) {
      start = Math.max(0, Math.floor((layers.length - 1) / batch) * batch);
    }
    lastSelection = selectedId;
  });
  const shown = $derived(layers.slice(Math.max(0, layers.length - start - batch), layers.length - start).reverse());
</script>

<aside class="panel" aria-label="Layers">
  <div class="panel-heading">
    <h2>Layers <span>{layers.length}</span></h2>
    <button class="close" type="button" data-testid="design-close-layers" onclick={onClose} aria-label="Close layers">×</button>
  </div>
  <div class="layer-list">
    {#each shown as layer (layer.id)}
      <div class="layer" class:active={layer.id === selectedId} class:hidden={layer.hidden}>
        <button class="layer-name" type="button" aria-pressed={layer.id === selectedId} onclick={() => onSelect(layer.id)}
          data-testid={`design-layer-${layer.id}`}>
          <span class="layer-icon" style:--layer-icon="var(--icon-url-{names[layer.kind]})" aria-hidden="true"></span>
          <span>{layer.name}</span>
          {#if layer.locked}<span class="locked-dot" title="Locked" aria-label="Locked"></span>{/if}
        </button>
        {#if layer.id === selectedId}
          <EmbedIconButton icon={layer.hidden ? 'hidden' : 'visible'} label={layer.hidden ? 'Show layer' : 'Hide layer'} testId="design-toggle-layer-visibility"
            onclick={() => onChange({ ...layer, hidden: !layer.hidden })} />
          <EmbedIconButton icon="lock" label={layer.locked ? 'Unlock layer' : 'Lock layer'} testId="design-toggle-layer-lock" pressed={!!layer.locked}
            onclick={() => onChange({ ...layer, locked: !layer.locked })} />
          <!-- ui-control-visibility: allow shared icon buttons expose their testId. -->
        {/if}
      </div>
    {/each}
  </div>
  {#if layers.length > batch}
    <div class="range">
      <button type="button" disabled={start === 0} data-testid="design-previous-layers" onclick={() => start -= batch} aria-label="Previous layers">‹</button>
      <span>{start + 1}–{Math.min(start + batch, layers.length)} of {layers.length}</span>
      <button type="button" disabled={start + batch >= layers.length} data-testid="design-next-layers" onclick={() => start += batch} aria-label="More layers">›</button>
    </div>
  {/if}
  <div class="order">
    <EmbedIconButton icon="up" label="Bring forward" testId="design-bring-layer-forward" disabled={selectedIndex < 0 || selectedIndex === layers.length - 1 || layers[selectedIndex].locked}
      onclick={() => onOrder(1)} />
    <EmbedIconButton icon="down" label="Send backward" testId="design-send-layer-backward" disabled={selectedIndex <= 0 || layers[selectedIndex].locked}
      onclick={() => onOrder(-1)} />
    <!-- ui-control-visibility: allow shared icon buttons expose their testId. -->
  </div>
</aside>

<style>
  .panel { display: flex; flex-direction: column; min-height: 0; height: 100%; padding: 14px 10px 10px; box-sizing: border-box; }
  .panel-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 6px 10px; }
  h2 { font-size: .875rem; margin: 0; display: flex; align-items: center; gap: 8px; }
  h2 span { color: var(--color-font-tertiary); font-weight: 400; font-size: .75rem; }
  .close { display: none; }
  .layer-list { flex: 1; min-height: 0; overflow: auto; }
  .layer { display: flex; min-width: 0; align-items: center; border-radius: var(--radius-3); gap: 2px; padding-right: 3px; }
  .layer.active { background: color-mix(in srgb, var(--color-primary-start) 14%, var(--color-grey-0)); }
  .layer.hidden .layer-name { opacity: .65; }
  .layer-name {
    display: flex; align-items: center; justify-content: flex-start; gap: 8px; flex: 1; min-width: 0; min-height: 39px;
    border: 0; background: transparent; color: inherit; text-align: start;
    border-radius: inherit; margin: 0; filter: none; padding: 0 7px; cursor: pointer; font-size: .75rem;
  }
  .layer-name:hover { background: var(--color-grey-20); scale: 1; }
  .layer-name span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .layer-icon { display: block; width: 15px; height: 15px; flex: none; background: var(--color-font-tertiary); mask: var(--layer-icon) center / contain no-repeat; }
  .locked-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--color-primary-start); }
  .layer :global(.embed-icon-button) { width: 30px; height: 30px; padding: 6px; }
  .layer :global(.embed-icon-button-icon) { width: 17px; height: 17px; }
  .order { display: flex; gap: 7px; padding: 8px 4px 0; border-top: 1px solid var(--color-grey-25); }
  .order :global(.embed-icon-button) { width: 36px; height: 36px; padding: 8px; }
  .range { display: flex; justify-content: space-between; align-items: center; font-size: .75rem; padding: 4px; }
  .range button, .close {
    border: 0; border-radius: 50%; background: var(--color-grey-20); color: inherit;
    font-size: 1.2rem; width: 36px; min-width: 0; height: 36px; margin: 0; padding: 0; filter: none; cursor: pointer;
  }
  .range button:disabled { opacity: .4; cursor: default; }
  @container fullscreen (max-width: 740px) {
    .panel { padding-top: 8px; }
    .close { display: block; }
    .layer-name { min-height: 44px; font-size: .875rem; }
    .layer :global(.embed-icon-button) { width: 44px; height: 44px; }
  }
</style>
