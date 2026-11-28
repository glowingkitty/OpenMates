<script lang="ts">
  import { tick } from 'svelte';
  import { designFonts, MIN_LAYER_SIZE, type DesignFont, type DesignLayer } from './designDocument';

  interface Props {
    layer: DesignLayer | null;
    onChange: (layer: DesignLayer) => void;
    onClose: () => void;
  }

  let { layer, onChange, onClose }: Props = $props();
  const componentId = $props.id();
  const fontId = `${componentId}-font`;
  let textInput: HTMLTextAreaElement | undefined = $state();
  const geometry = [{ key: 'x', label: 'X' }, { key: 'y', label: 'Y' }, { key: 'width', label: 'Width' },
    { key: 'height', label: 'Height' }, { key: 'rotation', label: 'Angle' }] as const;
  const colors = ['#17294b', '#4867cd', '#397360', '#ff775c', '#f6d994', '#fff0ce'];

  export async function focusText() {
    await tick();
    textInput?.focus();
  }

  function numberValue(event: Event, value: number, min = -12000, max = 12000) {
    const input = event.currentTarget as HTMLInputElement;
    const number = input.valueAsNumber;
    const result = Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : value;
    input.value = String(Math.round(result * 10) / 10);
    return result;
  }
</script>

<aside class="panel" aria-label="Properties">
  <div class="panel-heading">
    <h2>Properties</h2>
    <button class="close" type="button" data-testid="design-close-properties" onclick={onClose} aria-label="Close properties">×</button>
  </div>
  {#if layer}
    {@const selected = layer}
    {#key selected.id}
      <div class="selection-name">{selected.name}</div>
      {#if selected.locked}
        <p class="hint">Unlock this layer to edit it.</p>
      {:else}
        {#if selected.kind === 'text'}
          <div class="property-section">
            <label class="field">Text
              <textarea bind:this={textInput} value={selected.text} maxlength="1000" rows="2"
                data-testid="design-property-text" onchange={(event) => onChange({ ...selected, text: event.currentTarget.value })}></textarea>
            </label>
            <div class="fields">
              <div class="field">
                <label for={fontId}>Font</label>
                <select id={fontId} value={selected.font}
                  data-testid="design-property-font" onchange={(event) => onChange({ ...selected, font: event.currentTarget.value as DesignFont })}>
                  {#each Object.keys(designFonts) as font}<option value={font}>{font}</option>{/each}
                </select>
              </div>
              <label class="field">Size
                <input type="number" min="6" max="480" value={selected.fontSize}
                  data-testid="design-property-font-size" onchange={(event) => onChange({ ...selected, fontSize: numberValue(event, selected.fontSize, 6, 480) })} />
              </label>
            </div>
          </div>
        {/if}
        {#if selected.kind !== 'image'}
          <div class="property-section">
            <label class="color-field">Color
              <input type="color" value={selected.color}
                data-testid="design-property-color" onchange={(event) => onChange({ ...selected, color: event.currentTarget.value })} />
            </label>
            <div class="swatches">
              {#each colors as color}
                <button type="button" title={color} aria-label={`Set color ${color}`} aria-pressed={selected.color === color}
                  data-testid={`design-swatch-${color.slice(1)}`} style:--swatch={color} onclick={() => onChange({ ...selected, color })}></button>
              {/each}
            </div>
          </div>
        {/if}
        <div class="property-section fields">
          {#each geometry as { key, label }}
            <label class="field">{label}
              <input type="number" step="any" value={Math.round(selected[key] * 10) / 10}
                min={key === 'width' || key === 'height' ? MIN_LAYER_SIZE : undefined}
                data-testid={`design-property-${key}`} onchange={(event) => onChange({ ...selected, [key]: numberValue(event, selected[key],
                  key === 'width' || key === 'height' ? MIN_LAYER_SIZE : key === 'rotation' ? -180 : -12000,
                  key === 'rotation' ? 180 : 12000) })} />
            </label>
          {/each}
        </div>
      {/if}
    {/key}
  {:else}
    <p class="hint">Select a layer to see its properties.</p>
  {/if}
</aside>

<style>
  .panel { min-height: 0; height: 100%; overflow: auto; padding: 14px 13px; box-sizing: border-box; }
  .panel-heading { display: flex; align-items: center; justify-content: space-between; padding-bottom: 10px; }
  h2 { font-size: .875rem; margin: 0; }
  .selection-name { font-size: .8rem; color: var(--color-font-tertiary); overflow-wrap: anywhere; }
  .hint { font-size: .8rem; color: var(--color-font-tertiary); margin-block: 10px; }
  .property-section { padding-block: 11px; border-bottom: 1px solid var(--color-grey-25); }
  .field { display: grid; gap: 4px; min-width: 0; color: var(--color-font-tertiary); font-size: .75rem; }
  .fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
  textarea { resize: vertical; }
  textarea, input, select {
    font-family: inherit; box-sizing: border-box; width: 100%; min-width: 0; padding: 6px;
    border: 1px solid var(--color-grey-30); border-radius: var(--radius-3);
    background: var(--color-grey-10); color: var(--color-font-primary); font-size: 1rem;
  }
  .property-section > .fields { margin-top: 8px; }
  .color-field { display: flex; align-items: center; justify-content: space-between; font-size: .75rem; }
  input[type='color'] { width: 42px; height: 33px; padding: 2px; cursor: pointer; }
  .swatches { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 7px; }
  .swatches button {
    background: var(--swatch); border: 1px solid var(--color-grey-30); width: 24px; min-width: 0; height: 24px; margin: 0; padding: 0; filter: none; border-radius: 50%; cursor: pointer;
  }
  .swatches button[aria-pressed='true'] { outline: 2px solid var(--color-primary-start); outline-offset: 1px; }
  .close { display: none; }
  @container fullscreen (max-width: 740px) {
    .panel { padding-top: 8px; }
    .close {
      display: block; border: 0; border-radius: 50%; background: var(--color-grey-20); color: inherit;
      font-size: 1.2rem; width: 36px; min-width: 0; height: 36px; margin: 0; padding: 0; filter: none; cursor: pointer;
    }
    .swatches button { width: 34px; height: 34px; }
  }
</style>
