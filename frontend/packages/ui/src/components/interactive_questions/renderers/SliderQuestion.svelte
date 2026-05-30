<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/SliderQuestion.svelte

  Slider-type interactive question component (numeric scale).
  Renders a horizontal range input with interactive value preview and tick labels.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { SliderQuestionData } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: SliderQuestionData;
    value: { id: string; value: number } | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: number | null;
  }>();

  // Internal reactive slider value state
  let sliderVal = $state<number>(0);

  $effect.pre(() => {
    sliderVal = data.default ?? Math.round((data.min + data.max) / 2);
  });

  // Sync if locked/answered
  $effect(() => {
    if (disabled && answeredValue !== null) {
      sliderVal = answeredValue;
      isValid = true;
    }
  });

  function handleChange(val: number) {
    if (disabled) return;
    sliderVal = val;
    isValid = true;
    value = { id: data.id, value: sliderVal };
  }
</script>

<div class="slider-question" class:disabled>
  <div class="slider-wrapper">
    <input
      type="range"
      min={data.min}
      max={data.max}
      step={data.step ?? 1}
      value={sliderVal}
      {disabled}
      oninput={(e) => handleChange(parseFloat((e.target as HTMLInputElement).value))}
      class="range-input"
    />
  </div>

  <div class="slider-meta">
    <div class="current-value">
      Selected: <span class="val-num">{sliderVal}</span>
      {#if data.labels && data.labels[sliderVal]}
        <span class="val-label">({data.labels[sliderVal]})</span>
      {/if}
    </div>

    {#if data.labels}
      <div class="labels-track">
        {#each Object.entries(data.labels) as [key, label]}
          <div class="tick-label" style="left: {((parseFloat(key) - data.min) / (data.max - data.min)) * 100}%">
            <span class="tick-mark">|</span>
            <span class="tick-text">{label}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .slider-wrapper {
    position: relative;
    padding: var(--spacing-16, 16px) 0;
    width: 100%;
  }

  .range-input {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--color-grey-30, #dee2e6);
    outline: none;
    transition: background 0.15s ease;
  }

  .range-input::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--color-primary, #4dabf7);
    cursor: pointer;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    transition: transform 0.1s ease;
  }

  .range-input::-webkit-slider-thumb:hover {
    transform: scale(1.15);
  }

  .range-input:disabled::-webkit-slider-thumb {
    background: var(--color-grey-40, #ced4da);
    cursor: not-allowed;
    transform: none;
  }

  .slider-meta {
    margin-top: var(--spacing-12, 12px);
    width: 100%;
  }

  .current-value {
    text-align: center;
    font-size: var(--font-size-p, 15px);
    font-weight: 500;
    color: var(--color-font-primary, #212529);
    margin-bottom: var(--spacing-16, 16px);
  }

  .val-num {
    color: var(--color-primary, #4dabf7);
    font-weight: 700;
  }

  .val-label {
    font-style: italic;
    font-weight: 400;
    color: var(--color-font-secondary, #495057);
    margin-left: var(--spacing-4, 4px);
  }

  .labels-track {
    position: relative;
    height: 35px;
    width: 100%;
    margin-top: var(--spacing-16, 16px);
  }

  .tick-label {
    position: absolute;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    pointer-events: none;
  }

  .tick-mark {
    font-size: 10px;
    color: var(--color-grey-40, #ced4da);
    line-height: 1;
    margin-bottom: 2px;
  }

  .tick-text {
    font-size: 11px;
    color: var(--color-font-secondary, #495057);
    white-space: nowrap;
  }

  .disabled {
    opacity: 0.9;
  }
</style>
