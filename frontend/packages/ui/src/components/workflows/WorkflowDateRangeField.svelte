<script lang="ts">
  import { text } from '../../i18n/translations';
  import ResultsDateRangeFilter from '../embeds/ResultsDateRangeFilter.svelte';
  import { record } from './workflowBuilder';

  let {
    start,
    end,
    timezone,
    maxOffsetDays = 13,
    dateTimeBounds = false,
    onChange
  }: {
    start: unknown;
    end: unknown;
    timezone: string;
    maxOffsetDays?: number;
    dateTimeBounds?: boolean;
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
  type RangeMode = 'none' | 'today' | 'next-week' | 'specific';

  function runtimeDateOrdinal(value: unknown): number | null {
    const dynamic = String(record(value).$date ?? '');
    if (dynamic === 'today' || dynamic === 'today_end') return todayOrdinal;
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

  function dateValue(day: number, endOfDay: boolean): string {
    const date = isoDate(day);
    return dateTimeBounds ? `${date}T${endOfDay ? '23:59:59' : '00:00:00'}[${timezone}]` : date;
  }

  function relativeDate(value: unknown): string {
    return String(record(value).$date ?? '');
  }

  let mode = $state<RangeMode>('none');
  let selectedStart = $state(0);
  let selectedEnd = $state(0);
  let initializedValues = '';

  $effect(() => {
    const valuesKey = `${timezone}:${JSON.stringify(start)}:${JSON.stringify(end)}`;
    if (initializedValues === valuesKey) return;
    if (relativeDate(start) === 'today' && ['today', 'today_end'].includes(relativeDate(end))) mode = 'today';
    else if (relativeDate(start) === 'next_week_start' && relativeDate(end) === 'next_week_end') mode = 'next-week';
    else mode = start || end ? 'specific' : 'none';
    selectedStart = Math.max(todayOrdinal, Math.min(maxOrdinal, runtimeDateOrdinal(start) ?? todayOrdinal));
    selectedEnd = Math.max(selectedStart, Math.min(maxOrdinal, runtimeDateOrdinal(end) ?? selectedStart));
    initializedValues = valuesKey;
  });

  function useToday(): void {
    mode = 'today';
    selectedStart = todayOrdinal;
    selectedEnd = todayOrdinal;
    onChange(
      { $date: 'today', format: dateTimeBounds ? 'datetime' : 'date' },
      { $date: dateTimeBounds ? 'today_end' : 'today', format: dateTimeBounds ? 'datetime' : 'date' }
    );
  }

  function useNextWeek(): void {
    mode = 'next-week';
    const weekday = (new Date(todayOrdinal * dayMs).getUTCDay() + 6) % 7;
    selectedStart = todayOrdinal + 7 - weekday;
    selectedEnd = selectedStart + 6;
    onChange(
      { $date: 'next_week_start', format: dateTimeBounds ? 'datetime' : 'date' },
      { $date: 'next_week_end', format: dateTimeBounds ? 'datetime' : 'date' }
    );
  }

  function useSpecific(): void {
    mode = 'specific';
    onChange(dateValue(selectedStart, false), dateValue(selectedEnd, true));
  }

  function changeRange(side: 'min' | 'max', day: number): void {
    if (side === 'min') selectedStart = day;
    else selectedEnd = day;
    onChange(dateValue(selectedStart, false), dateValue(selectedEnd, true));
  }
</script>

<div class="date-range" data-testid="workflow-date-range-field">
  <span class="label">{tr('date_range')}</span>
  <div class="range-modes" role="group" aria-label={tr('date_range')}>
    <button type="button" class:active={mode === 'today'} data-testid="workflow-date-range-today" onclick={useToday}>{tr('today')}</button>
    <button type="button" class:active={mode === 'next-week'} data-testid="workflow-date-range-next-week" onclick={useNextWeek}>{tr('next_week')}</button>
    <button type="button" class:active={mode === 'specific'} data-testid="workflow-date-range-specific" onclick={useSpecific}>{tr('specific_dates')}</button>
  </div>
  {#if mode === 'specific'}
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
  .range-modes { display:flex; flex-wrap:wrap; gap:var(--spacing-4); }
  .range-modes button { min-height:2.5rem; margin:0; padding:.45rem .9rem; border:0; border-radius:var(--radius-full); background:var(--color-grey-0); color:var(--color-font-secondary); box-shadow:var(--shadow-sm); font:inherit; font-size:max(16px, 1rem); cursor:pointer; }
  .range-modes button.active { background:var(--gradient-primary); color:var(--color-font-button); }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
</style>
