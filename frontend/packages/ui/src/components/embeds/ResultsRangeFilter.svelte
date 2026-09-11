<script lang="ts">
  interface Props {
    min: number;
    max: number;
    lower: number;
    upper: number;
    values: number[];
    step?: number;
    label: string;
    testId: string;
    formatValue: (value: number) => string;
    onChange: (side: "min" | "max", value: number) => void;
  }

  let { min, max, lower, upper, values, step = 1, label, testId, formatValue, onChange }: Props = $props();
  const binCount = 36;
  const clamp = (value: number) => Math.max(min, Math.min(max, value));
  const percentage = (value: number) => max > min ? ((clamp(value) - min) / (max - min)) * 100 : 0;
  let lowerPercent = $derived(percentage(lower));
  let upperPercent = $derived(percentage(upper));
  // Distribution depends only on source results; dragging changes colors, not binning.
  let bins = $derived.by(() => {
    const result = Array.from({ length: binCount }, () => ({ count: 0, values: [] as number[] }));
    for (const value of values) {
      if (!Number.isFinite(value) || value < min || value > max) continue;
      const index = max > min ? Math.min(binCount - 1, Math.floor(((value - min) / (max - min)) * binCount)) : 0;
      result[index].count += 1;
      result[index].values.push(value);
    }
    const largest = Math.max(1, ...result.map((bin) => bin.count));
    return result.map((bin) => ({ ...bin, height: Math.max(4, (bin.count / largest) * 56) }));
  });

  function update(side: "min" | "max", event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const candidate = clamp(input.valueAsNumber);
    const value = side === "min" ? Math.min(candidate, upper) : Math.max(candidate, lower);
    input.value = String(value);
    onChange(side, value);
  }
</script>

<div class="distribution-filter" data-testid={`${testId}-control`} role="group" aria-label={label}>
  <div class="histogram" aria-hidden="true">
    {#each bins as bin}
      <span class="distribution-bar" class:selected={bin.values.some((value) => value >= lower && value <= upper)} style:height={`${bin.height}px`}></span>
    {/each}
  </div>
  <div class="range-controls">
    <div class="range-track" aria-hidden="true"></div>
    <input class="range-input lower" class:at-end={lowerPercent === 100} type="range" {min} {max} {step} value={lower} disabled={max <= min} aria-label={`${label} minimum`} aria-valuetext={formatValue(lower)} data-testid={`${testId}-min`} oninput={(event) => update("min", event)} />
    <input class="range-input upper" type="range" {min} {max} {step} value={upper} disabled={max <= min} aria-label={`${label} maximum`} aria-valuetext={formatValue(upper)} data-testid={`${testId}-max`} oninput={(event) => update("max", event)} />
  </div>
  <div class="range-values">
    <output class="range-value" style:left={`${lowerPercent}%`} style:transform={`translateX(-${lowerPercent}%)`} data-testid={`${testId}-min-value`}>{formatValue(lower)}</output>
    <output class="range-value" style:left={`${upperPercent}%`} style:transform={`translateX(-${upperPercent}%)`} data-testid={`${testId}-max-value`}>{formatValue(upper)}</output>
  </div>
</div>

<style>
  .distribution-filter { width: 100%; min-width: 0; padding: var(--spacing-6) 0 var(--spacing-4); }
  .histogram { display: flex; align-items: flex-end; height: 56px; gap: 3px; margin: 0 14px var(--spacing-2); }
  .distribution-bar { flex: 1 1 0; min-width: 0; border-radius: 2px; background: var(--color-grey-50); }
  .distribution-bar.selected { background: var(--color-app-travel-start); }
  .range-controls { position: relative; height: 36px; }
  .range-track { position: absolute; inset: 15px 14px; height: 6px; border-radius: var(--radius-full); background: var(--color-grey-40); }
  .range-input { position: absolute; inset: 0; width: 100%; min-width: 0; max-width: none; height: 36px; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; appearance: none; -webkit-appearance: none; background: transparent; pointer-events: none; outline: none; }
  .range-input.lower { z-index: 2; }
  .range-input.upper { z-index: 3; }
  .range-input.lower.at-end, .range-input:focus-visible { z-index: 4; }
  .range-input::-webkit-slider-runnable-track { height: 6px; background: transparent; border: 0; }
  .range-input::-moz-range-track { height: 6px; background: transparent; border: 0; }
  .range-input::-webkit-slider-thumb { appearance: none; -webkit-appearance: none; height: 28px; width: 28px; margin-top: -11px; border: 0; border-radius: var(--radius-full); background: var(--color-app-travel-start); box-shadow: none; pointer-events: auto; cursor: ew-resize; }
  .range-input::-moz-range-thumb { height: 28px; width: 28px; border: 0; border-radius: var(--radius-full); background: var(--color-app-travel-start); box-shadow: none; pointer-events: auto; cursor: ew-resize; }
  .range-input:focus-visible::-webkit-slider-thumb { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .range-input:focus-visible::-moz-range-thumb { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .range-values { position: relative; min-height: 3em; margin: 0 14px; color: var(--color-font-primary); font-size: var(--font-size-small); font-weight: 700; }
  .range-value { position: absolute; top: 0; width: max-content; max-width: 48%; line-height: 1.4; text-align: center; white-space: pre-line; overflow-wrap: anywhere; }
</style>
