<script lang="ts">
  import { text } from '../../i18n/translations';
  import ResultsDateRangeFilter from '../embeds/ResultsDateRangeFilter.svelte';
  import { record } from './workflowBuilder';

  let {
    start,
    end,
    timezone,
    maxOffsetDays = 13,
    onChange
  }: {
    start: unknown;
    end: unknown;
    timezone: string;
    maxOffsetDays?: number;
    onChange: (start: unknown, end: unknown) => void;
  } = $props();

  const dayMs = 86_400_000;
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  function todayInTimezone(zone: string): number {
    try {
      const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
      const part = (type: 'year' | 'month' | 'day') => Number(parts.find(item => item.type === type)?.value);
      return Math.floor(Date.UTC(part('year'), part('month') - 1, part('day')) / dayMs);
    } catch {
      const now = new Date();
      return Math.floor(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) / dayMs);
    }
  }
  let todayOrdinal = $derived(todayInTimezone(timezone));
  let maxOrdinal = $derived(todayOrdinal + maxOffsetDays);

  function runtimeDateOrdinal(value: unknown): number | null {
    const dynamic = String(record(value).$date ?? '');
    if (dynamic === 'today') return todayOrdinal;
    if (dynamic === 'next_week_start' || dynamic === 'next_week_end') {
      const weekday = (new Date(todayOrdinal * dayMs).getUTCDay() + 6) % 7;
      const nextMonday = todayOrdinal + 7 - weekday;
      return dynamic === 'next_week_end' ? nextMonday + 6 : nextMonday;
    }
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return null;
    const [year, month, day] = value.slice(0, 10).split('-').map(Number);
    return Math.floor(Date.UTC(year, month - 1, day) / dayMs);
  }

  function isoDate(day: number): string {
    return new Date(day * dayMs).toISOString().slice(0, 10);
  }

  function isToday(value: unknown): boolean {
    return String(record(value).$date ?? '') === 'today';
  }

  let specific = $state(false);
  let selectedStart = $state(0);
  let selectedEnd = $state(0);
  let initializedTimezone = '';

  $effect(() => {
    if (initializedTimezone === timezone) return;
    specific = !(isToday(start) && isToday(end)) && Boolean(start || end);
    selectedStart = Math.max(todayOrdinal, Math.min(maxOrdinal, runtimeDateOrdinal(start) ?? todayOrdinal));
    selectedEnd = Math.max(selectedStart, Math.min(maxOrdinal, runtimeDateOrdinal(end) ?? selectedStart));
    initializedTimezone = timezone;
  });

  function useToday(): void {
    specific = false;
    selectedStart = todayOrdinal;
    selectedEnd = todayOrdinal;
    const today = { $date: 'today', format: 'date' };
    onChange(today, today);
  }

  function useSpecific(): void {
    specific = true;
    onChange(isoDate(selectedStart), isoDate(selectedEnd));
  }

  function changeRange(side: 'min' | 'max', day: number): void {
    if (side === 'min') selectedStart = day;
    else selectedEnd = day;
    onChange(isoDate(selectedStart), isoDate(selectedEnd));
  }
</script>

<div class="date-range" data-testid="workflow-date-range-field">
  <span class="label">{tr('date_range')}</span>
  <div class="range-modes" role="group" aria-label={tr('date_range')}>
    <button type="button" class:active={!specific} data-testid="workflow-date-range-today" onclick={useToday}>{tr('today')}</button>
    <button type="button" class:active={specific} data-testid="workflow-date-range-specific" onclick={useSpecific}>{tr('specific_dates')}</button>
  </div>
  {#if specific}
    <ResultsDateRangeFilter
      min={todayOrdinal}
      max={maxOrdinal}
      lower={selectedStart}
      upper={selectedEnd}
      label={tr('date_range')}
      testId="workflow-date-range"
      onChange={changeRange}
    />
  {/if}
</div>

<style>
  .date-range { grid-column:1/-1; display:grid; gap:var(--spacing-6); min-width:0; text-align:start; }
  .label { font-size:max(16px, 1rem); font-weight:650; }
  .range-modes { display:flex; gap:var(--spacing-4); }
  .range-modes button { min-height:2.5rem; margin:0; padding:.45rem .9rem; border:0; border-radius:var(--radius-full); background:var(--color-grey-0); color:var(--color-font-secondary); box-shadow:var(--shadow-sm); font:inherit; font-size:max(16px, 1rem); cursor:pointer; }
  .range-modes button.active { background:var(--gradient-primary); color:var(--color-font-button); }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
</style>
