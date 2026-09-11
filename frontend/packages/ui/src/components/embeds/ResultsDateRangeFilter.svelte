<script lang="ts">
  interface Props {
    min: number;
    max: number;
    lower: number;
    upper: number;
    label: string;
    testId: string;
    onChange: (side: "min" | "max", value: number) => void;
  }
  let { min, max, lower, upper, label, testId, onChange }: Props = $props();
  const dayMs = 86_400_000;
  const date = (day: number) => new Date(day * dayMs);
  const monthOf = (day: number) => { const value = date(day); return value.getUTCFullYear() * 12 + value.getUTCMonth(); };
  let selectedMonth = $state<number | null>(null);
  let rangeStart = $state<number | null>(null);
  let month = $derived(Math.max(monthOf(min), Math.min(monthOf(max), selectedMonth ?? monthOf(lower))));
  let monthStart = $derived(new Date(Date.UTC(Math.floor(month / 12), month % 12, 1)));
  let monthTitle = $derived(monthStart.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" }));
  let days = $derived.by(() => {
    const firstDay = Math.floor(monthStart.getTime() / dayMs);
    const leading = (monthStart.getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(Math.floor(month / 12), month % 12 + 1, 0)).getUTCDate();
    return Array.from({ length: Math.ceil((leading + count) / 7) * 7 }, (_, index) => {
      const day = firstDay + index - leading;
      return { day, number: date(day).getUTCDate(), inMonth: index >= leading && index < leading + count };
    });
  });
  const weekdayLabels = Array.from({ length: 7 }, (_, index) => new Date(Date.UTC(2026, 0, 5 + index)).toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" }));
  const fullDate = (day: number) => date(day).toLocaleDateString(undefined, { dateStyle: "medium", timeZone: "UTC" });

  $effect(() => {
    // Clearing filters outside this control must also cancel a partial selection.
    if (rangeStart !== null && (lower !== rangeStart || upper !== rangeStart)) rangeStart = null;
  });

  function selectDay(day: number) {
    if (rangeStart === null) {
      rangeStart = day;
      onChange("min", day);
      onChange("max", day);
    } else {
      onChange("min", Math.min(rangeStart, day));
      onChange("max", Math.max(rangeStart, day));
      rangeStart = null;
    }
  }
</script>

<div class="date-range-filter" data-testid={`${testId}-control`} role="group" aria-label={label}>
  <div class="month-navigation">
    <button type="button" class="month-arrow" aria-label="Previous month" disabled={month <= monthOf(min)} onclick={() => { selectedMonth = month - 1; }}><span aria-hidden="true">‹</span></button>
    <span aria-live="polite">{monthTitle}</span>
    <button type="button" class="month-arrow" aria-label="Next month" disabled={month >= monthOf(max)} onclick={() => { selectedMonth = month + 1; }}><span aria-hidden="true">›</span></button>
  </div>
  <div class="month-grid">
    {#each weekdayLabels as weekday}<span class="weekday">{weekday}</span>{/each}
    {#each days as item}
      {#if item.inMonth}
        <button type="button" class="day" class:in-range={item.day >= lower && item.day <= upper} class:range-boundary={item.day === lower || item.day === upper} disabled={item.day < min || item.day > max} aria-label={fullDate(item.day)} aria-pressed={item.day >= lower && item.day <= upper} data-day={item.day} onclick={() => selectDay(item.day)}>{item.number}</button>
      {:else}<span aria-hidden="true"></span>{/if}
    {/each}
  </div>
  <p class="selection" aria-live="polite">{fullDate(lower)} – {fullDate(upper)}</p>
  <p class="selection-help">{rangeStart === null ? "Select a start date, then an end date." : "Select an end date."}</p>
</div>

<style>
  .date-range-filter { width: 100%; min-width: 0; color: var(--color-font-primary); font-size: var(--font-size-small); }
  .month-navigation { display: flex; align-items: center; justify-content: space-between; min-height: 44px; margin-bottom: var(--spacing-4); color: var(--color-font-secondary); font-weight: 700; }
  .month-arrow { display: grid; place-items: center; width: 36px; min-height: 36px; margin: 0; padding: 0; background: transparent; border: 0; border-radius: var(--radius-full); box-shadow: none; color: var(--color-font-secondary); font: inherit; font-size: var(--font-size-h2); cursor: pointer; }
  .month-arrow:disabled { opacity: .3; cursor: default; }
  .month-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: var(--spacing-2) 0; }
  .weekday { padding: var(--spacing-4) 0; color: var(--color-font-secondary); font-size: var(--font-size-xxs); text-align: center; overflow: hidden; }
  .day { min-width: 0; min-height: 36px; margin: 0; padding: var(--spacing-2) 0; border: 0; border-radius: var(--radius-2); box-shadow: none; background: transparent; color: var(--color-font-primary); font: inherit; cursor: pointer; }
  .day.in-range { background: color-mix(in srgb, var(--color-primary-start) 15%, transparent); }
  /* As on canonical primary buttons, text on the blue gradient stays white in both themes. */
  .day.range-boundary { background: var(--gradient-primary); color: var(--color-font-button); font-weight: 700; border-radius: var(--radius-full); }
  .day:disabled { opacity: .25; cursor: default; }
  .day:hover:not(:disabled):not(.range-boundary) { background: var(--color-grey-30); }
  .day:focus-visible, .month-arrow:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .selection { margin: var(--spacing-8) 0 var(--spacing-2); font-weight: 700; font-size: var(--font-size-xs); text-align: center; }
  .selection-help { margin: 0; color: var(--color-font-secondary); font-size: var(--font-size-xxs); text-align: center; }
</style>
