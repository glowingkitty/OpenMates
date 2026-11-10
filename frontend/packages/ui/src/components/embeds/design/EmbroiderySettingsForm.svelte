<!--
  frontend/packages/ui/src/components/embeds/design/EmbroiderySettingsForm.svelte

  "Change settings": width, hoop and fabric for a new conversion of the same
  graphic. Applying only reports the chosen values; the parent sends them as an
  ordinary follow-up turn, so the existing result stays untouched.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import { text } from '@repo/ui';
  import {
    EMBROIDERY_BORDERS_MM, EMBROIDERY_FABRICS, EMBROIDERY_HOOPS, EMBROIDERY_MAX_WIDTH_MM, EMBROIDERY_MIN_WIDTH_MM,
    formatHoop, type EmbroideryFabric, type EmbroideryHoop, type EmbroiderySettings,
  } from './embroideryDesign';

  interface Props {
    widthMm: number;
    hoop: EmbroideryHoop;
    fabric: EmbroideryFabric;
    borderMm: number;
    submitting: boolean;
    onApply: (settings: EmbroiderySettings) => void;
  }
  let { widthMm, hoop, fabric, borderMm, submitting, onApply }: Props = $props();

  // The form starts from the opened result and then belongs to the user.
  let width = $state(untrack(() => Math.round(widthMm)));
  let selectedHoop = $state<EmbroideryHoop>(untrack(() => hoop));
  let selectedFabric = $state<EmbroideryFabric>(untrack(() => fabric));
  let selectedBorder = $state<number>(untrack(() => borderMm));
  const widthValid = $derived(
    Number.isFinite(width) && width >= EMBROIDERY_MIN_WIDTH_MM && width <= EMBROIDERY_MAX_WIDTH_MM,
  );
  // A current border outside the offered widths stays selectable so it is never lost silently.
  const borderOptions = $derived(
    (EMBROIDERY_BORDERS_MM as readonly number[]).includes(borderMm) ? [...EMBROIDERY_BORDERS_MM] : [...EMBROIDERY_BORDERS_MM, borderMm].sort((a, b) => a - b),
  );
  const uid = $props.id();

  function apply(event: SubmitEvent) {
    event.preventDefault();
    if (!widthValid || submitting) return;
    onApply({ widthMm: Math.round(width), hoop: selectedHoop, fabric: selectedFabric, borderMm: selectedBorder });
  }
</script>

<form class="settings" data-testid="design-embroidery-settings" onsubmit={apply}>
  <h4>{$text('embeds.design.embroidery.change_settings')}</h4>
  <div class="fields">
    <label for={`${uid}-width`}>
      <span>{$text('embeds.design.embroidery.width')}</span>
      <input
        id={`${uid}-width`}
        type="number"
        inputmode="numeric"
        min={EMBROIDERY_MIN_WIDTH_MM}
        max={EMBROIDERY_MAX_WIDTH_MM}
        step="1"
        bind:value={width}
        aria-invalid={!widthValid}
        data-testid="design-embroidery-width"
      />
    </label>
    <label for={`${uid}-hoop`}>
      <span>{$text('embeds.design.embroidery.hoop')}</span>
      <select id={`${uid}-hoop`} bind:value={selectedHoop} data-testid="design-embroidery-hoop">
        {#each EMBROIDERY_HOOPS as option (option)}
          <option value={option}>{option === 'none' ? $text('embeds.design.embroidery.hoop_none') : formatHoop(option)}</option>
        {/each}
      </select>
    </label>
    <label for={`${uid}-fabric`}>
      <span>{$text('embeds.design.embroidery.fabric')}</span>
      <select id={`${uid}-fabric`} bind:value={selectedFabric} data-testid="design-embroidery-fabric">
        {#each EMBROIDERY_FABRICS as option (option)}
          <option value={option}>{$text(`embeds.design.embroidery.fabric_${option}`)}</option>
        {/each}
      </select>
    </label>
    <label for={`${uid}-border`}>
      <span>{$text('embeds.design.embroidery.border')}</span>
      <select id={`${uid}-border`} bind:value={selectedBorder} data-testid="design-embroidery-border">
        {#each borderOptions as option (option)}
          <option value={option}>{option === 0 ? $text('embeds.design.embroidery.border_none') : $text('embeds.design.embroidery.border_mm', { values: { width: option } })}</option>
        {/each}
      </select>
    </label>
  </div>
  {#if !widthValid}
    <p class="invalid" role="alert">
      {$text('embeds.design.embroidery.width_range', { values: { min: EMBROIDERY_MIN_WIDTH_MM, max: EMBROIDERY_MAX_WIDTH_MM } })}
    </p>
  {/if}
  <button type="submit" class="apply" data-testid="design-embroidery-apply" disabled={!widthValid || submitting}>
    {$text('embeds.design.embroidery.apply')}
  </button>
</form>

<style>
  .settings { width: 100%; display: flex; flex-direction: column; gap: var(--spacing-5); container-type: inline-size; }
  h4 { margin: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .fields { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--spacing-5); }
  label { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  input, select {
    box-sizing: border-box;
    width: 100%;
    min-height: 44px;
    padding: 0 var(--spacing-5);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
  }
  input[aria-invalid="true"] { border-color: var(--color-error); }
  input:focus-visible, select:focus-visible, .apply:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .invalid { margin: 0; font-size: var(--font-size-xxs); color: var(--color-error); }
  .apply {
    align-self: flex-start;
    min-height: 44px;
    padding: 0 var(--spacing-10);
    border: 0;
    border-radius: var(--radius-4);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    font-weight: 650;
    cursor: pointer;
  }
  .apply:disabled { opacity: 0.5; cursor: not-allowed; }
  @container (min-width: 28rem) {
    .fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
