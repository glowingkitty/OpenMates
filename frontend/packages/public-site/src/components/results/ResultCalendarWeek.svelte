<!-- One weekly calendar presentation for assistant results and event artifacts. -->
<script lang="ts">
  import { buildCalendarWeekDays, calendarEndMinutes, calendarTime, calendarWeekNumber, calendarWeeksWithEntries, weekStartOrdinal, type CalendarWeekEntry } from './calendarWeek';

  interface Props {
    entries: CalendarWeekEntry[];
    onOpen: (ref: string) => void;
    onHover: (ref: string | null) => void;
    focusRef?: string;
    selectedRef?: string | null;
    hoveredRef?: string | null;
    compact?: boolean;
    interactive?: boolean;
    showNavigation?: boolean;
    locale?: string;
    labels?: { week: string; previous: string; next: string; primary: string; context: string; empty: string };
  }
  let { entries, onOpen, onHover, focusRef, selectedRef = null, hoveredRef = null, compact = false,
    interactive = true, showNavigation = true, locale,
    labels = { week: 'Week', previous: 'Previous week', next: 'Next week', primary: 'Primary event', context: 'Context event', empty: 'No dated events' },
  }: Props = $props();
  let selectedWeek = $state<number | null>(null);
  let calendarHeight = $state(160);
  let weeks = $derived(calendarWeeksWithEntries(entries));
  let focusWeek = $derived.by(() => {
    const item = focusRef ? entries.find(entry => entry.ref === focusRef) : undefined;
    return item ? weekStartOrdinal(item.dateOrdinal) : null;
  });
  let activeWeek = $derived(selectedWeek != null && weeks.includes(selectedWeek) ? selectedWeek : focusWeek ?? weeks[0] ?? null);
  let weekIndex = $derived(activeWeek == null ? -1 : weeks.indexOf(activeWeek));
  let days = $derived(activeWeek == null ? [] : buildCalendarWeekDays(activeWeek, entries));
  let allDayRows = $derived(Math.max(0, ...days.map(day => day.entries.filter(item => item.dateOnly).length)));
  let timed = $derived(days.flatMap(day => day.entries.filter(item => !item.dateOnly)));
  let startMinutes = $derived(timed.length ? Math.floor(Math.min(...timed.map(item => item.startMinutes)) / 60) * 60 : 8 * 60);
  let hours = $derived(timed.length ? Math.max(1, Math.min(24 - startMinutes / 60, Math.max(8, Math.ceil((Math.max(...timed.map(calendarEndMinutes)) - startMinutes) / 60)))) : 8);
  let hourLabels = $derived(Array.from({ length: hours + 1 }, (_, index) => startMinutes + index * 60));
  let headerHeight = $derived(compact ? 26 : 42);
  let allDayHeight = $derived(compact ? 36 : 64);
  let hourHeight = $derived(compact ? Math.max(3, (calendarHeight - 36 - headerHeight - allDayRows * allDayHeight) / hours) : 46);
  let rowTemplate = $derived([`${headerHeight}px`, ...(allDayRows ? [`${allDayRows * allDayHeight}px`] : []), ...(timed.length ? [`${hourHeight * hours}px`] : [])].join(' '));

  $effect(() => { void focusRef; selectedWeek = null; });
  $effect(() => {
    // Keep the filtered fallback instead of reviving a week hidden by filters.
    if (selectedWeek !== activeWeek) selectedWeek = activeWeek;
  });
  function moveWeek(delta: -1 | 1) {
    const next = weeks[weekIndex + delta];
    if (next != null) selectedWeek = next;
  }
  function dayLabel(ordinal: number) {
    return new Intl.DateTimeFormat(locale, { weekday: compact ? 'narrow' : 'short', timeZone: 'UTC' }).format(new Date(ordinal * 86_400_000));
  }
  function dayDate(ordinal: number) {
    return new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(ordinal * 86_400_000));
  }
  function itemLabel(item: CalendarWeekEntry) {
    return `${item.contextual ? labels.context : item.highlighted ? labels.primary : ''} ${item.title}, ${dayDate(item.dateOrdinal)}${item.dateOnly ? '' : `, ${calendarTime(item.startMinutes)}${item.endKnown ? ` – ${calendarTime(calendarEndMinutes(item))}` : ''}`}${item.location ? `, ${item.location}` : ''}`.trim();
  }
  function itemStyle(item: CalendarWeekEntry) {
    return `--calendar-item-top-hours: ${(item.startMinutes - startMinutes) / 60}; --calendar-item-height-hours: ${(calendarEndMinutes(item) - item.startMinutes) / 60}; --calendar-item-column: ${item.column ?? 0}; --calendar-item-columns: ${item.columnCount ?? 1};`;
  }
</script>

<div class="results-view-calendar" class:compact class:date-only={!timed.length}
  bind:clientHeight={calendarHeight} data-testid="embeds-results-view-calendar"
  style={`--calendar-row-template: ${rowTemplate}; --calendar-timeline-hours: ${hours}; --calendar-hour-height: ${hourHeight}px; --calendar-all-day-height: ${allDayHeight}px`}>
  {#if activeWeek != null}
    {@const week = calendarWeekNumber(activeWeek)}
    <header class="calendar-week-toolbar" class:static-toolbar={!showNavigation}>
      {#if showNavigation}<button type="button" aria-label={labels.previous} disabled={weekIndex <= 0} onclick={() => moveWeek(-1)}><span aria-hidden="true">&lt;</span></button>{/if}
      <strong data-testid="embeds-results-view-calendar-week-label">{labels.week} {week.week} {week.year}<span class="visually-hidden"> {dayDate(activeWeek)} – {dayDate(activeWeek + 6)}</span></strong>
      {#if showNavigation}<button type="button" aria-label={labels.next} disabled={weekIndex >= weeks.length - 1} onclick={() => moveWeek(1)}><span aria-hidden="true">&gt;</span></button>{/if}
    </header>
    <div class="calendar-week" class:date-only={!timed.length} data-testid="embeds-results-view-calendar-week">
      {#if timed.length}
        <div class="calendar-time-column" aria-hidden="true">
          <span></span>
          {#if allDayRows}<div></div>{/if}
          <div class="calendar-time-slots">{#each hourLabels as hour}<span>{calendarTime(hour)}</span>{/each}</div>
        </div>
      {/if}
      {#each days as day}
        <section class="calendar-day" class:today={day.isToday} data-testid="embeds-results-view-calendar-day" aria-label={dayDate(day.dateOrdinal)}>
          <header class="calendar-day-header" title={dayDate(day.dateOrdinal)}><span>{dayLabel(day.dateOrdinal)}</span> <span>{new Date(day.dateOrdinal * 86_400_000).getUTCDate()}</span></header>
          {#if allDayRows}
            <div class="calendar-date-only">
              {#each day.entries.filter(item => item.dateOnly) as item}
                <button type="button" class:highlighted={item.highlighted} class:contextual={item.contextual}
                  data-testid="embeds-results-view-calendar-date-only" data-context={item.contextual ? 'true' : 'false'} data-primary={item.highlighted && !item.contextual ? 'true' : 'false'}
                  aria-label={itemLabel(item)} title={itemLabel(item)} disabled={!interactive} onclick={() => onOpen(item.ref)}>
                  <strong>{item.title}</strong>{#if !compact}<span>{new Date(day.dateOrdinal * 86_400_000).toISOString().slice(0, 10)}</span>{/if}
                </button>
              {/each}
            </div>
          {/if}
          {#if timed.length}
            <div class="calendar-items">
              {#each day.entries.filter(item => !item.dateOnly) as item}
                <button type="button" class="calendar-item" class:highlighted={item.highlighted} class:contextual={item.contextual}
                  class:selected={selectedRef === item.ref} class:hovered={hoveredRef === item.ref}
                  data-testid="embeds-results-view-calendar-item" data-start-minutes={item.startMinutes} data-end-minutes={calendarEndMinutes(item)}
                  data-entry-category={item.category} data-selected={selectedRef === item.ref ? 'true' : 'false'}
                  data-context={item.contextual ? 'true' : 'false'} data-primary={item.highlighted && !item.contextual ? 'true' : 'false'}
                  style={itemStyle(item)} aria-label={itemLabel(item)} title={itemLabel(item)} disabled={!interactive}
                  onclick={() => onOpen(item.ref)} onpointerenter={() => interactive && onHover(item.ref)} onpointerleave={() => interactive && onHover(null)}
                  onfocus={() => onHover(item.ref)} onblur={() => onHover(null)}>
                  <span class="calendar-copy"><strong>{item.title}</strong>{#if item.location && !compact}<span class="calendar-location">{item.location}</span>{/if}</span>
                </button>
              {/each}
            </div>
          {/if}
        </section>
      {/each}
    </div>
  {:else}<div class="calendar-empty">{labels.empty}</div>{/if}
</div>

<style>
  .results-view-calendar { display: grid; grid-template-columns: minmax(0, 1fr); align-content: start; gap: 8px; height: 535px; min-height: 535px; max-height: 535px; box-sizing: border-box; min-width: 0; overflow: auto; padding: 14px 14px 24px; background: var(--color-grey-20); }
  .results-view-calendar.date-only { height: auto; min-height: 0; }
  .calendar-week-toolbar { display: grid; grid-template-columns: 28px minmax(0, 1fr) 28px; align-items: center; gap: 20px; justify-self: center; width: min(100%, 260px); min-height: 36px; position: sticky; left: 0; z-index: 1; }
  .calendar-week-toolbar strong { color: var(--color-font-tertiary); font-size: var(--font-size-small); font-weight: 500; text-align: center; white-space: nowrap; }
  .calendar-week-toolbar button { display: inline-grid; width: 28px; min-width: 28px; height: 28px; place-items: center; border: 0; border-radius: var(--radius-4); background: transparent; color: var(--color-font-tertiary); padding: 0; font: inherit; font-size: var(--font-size-h3); line-height: 1; cursor: pointer; }
  .calendar-week-toolbar button:hover:not(:disabled) { background: var(--color-grey-10); }
  .calendar-week-toolbar button:disabled { opacity: .35; cursor: default; }
  .static-toolbar { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .calendar-week { display: grid; grid-template-columns: 44px repeat(7, minmax(0, 1fr)); gap: 0; min-width: 620px; border-radius: var(--radius-6); }
  .calendar-week.date-only { grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .calendar-time-column, .calendar-day { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: var(--calendar-row-template); min-height: 0; min-width: 0; }
  .calendar-time-column { color: var(--color-font-primary); font-size: var(--font-size-xxs); font-weight: 500; }
  .calendar-time-slots { position: relative; display: grid; grid-auto-rows: var(--calendar-hour-height); }
  .calendar-time-slots span { align-self: start; justify-self: end; padding: 0 6px 0 0; transform: translateY(-.55em); }
  .calendar-day { gap: 0; padding: 0; border-radius: var(--radius-4); }
  .calendar-day.today { background: var(--color-grey-25); }
  .calendar-day-header { display: flex; align-items: center; justify-content: center; gap: .25rem; min-height: 42px; color: var(--color-font-primary); font-size: var(--font-size-small); font-weight: 500; white-space: nowrap; }
  .calendar-items { position: relative; min-height: calc(var(--calendar-hour-height) * var(--calendar-timeline-hours)); }
  .calendar-item { position: absolute; top: calc(var(--calendar-item-top-hours) * var(--calendar-hour-height)); left: calc(100% * var(--calendar-item-column) / var(--calendar-item-columns) + 3px); width: calc(100% / var(--calendar-item-columns) - 6px); min-width: 0; display: block; box-sizing: border-box; height: calc(var(--calendar-item-height-hours) * var(--calendar-hour-height)); min-height: 0; overflow: hidden; border: 0; border-left: 3px solid var(--color-error); border-radius: var(--radius-2); background: color-mix(in srgb, var(--color-error) 16%, var(--color-grey-20)); color: var(--color-font-primary); padding: 4px; text-align: left; font: inherit; box-shadow: none; cursor: pointer; }
  .calendar-item.highlighted, .calendar-item.hovered { border-color: var(--color-primary-start); }
  .calendar-item:focus-visible, .calendar-week-toolbar button:focus-visible, .calendar-date-only button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
  .calendar-copy { display: flex; flex-direction: column; min-width: 0; max-height: 100%; overflow: hidden; }
  .calendar-copy strong, .calendar-date-only strong { display: -webkit-box; overflow: hidden; overflow-wrap: anywhere; color: var(--color-font-primary); font-size: var(--font-size-small); font-weight: 500; line-height: 1.25; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; }
  .calendar-location { display: block; margin-top: 4px; overflow: hidden; color: var(--color-font-tertiary); font-size: var(--font-size-xxs); line-height: 1.25; white-space: nowrap; text-overflow: ellipsis; }
  .calendar-date-only { min-height: calc(var(--calendar-all-day-height) * var(--calendar-all-day-rows, 1)); }
  .calendar-date-only button { display: flex; flex-direction: column; width: calc(100% - 4px); height: calc(var(--calendar-all-day-height) - 8px); margin: 0 2px 8px; padding: .4rem; box-sizing: border-box; border: 0; border-left: 3px solid transparent; border-radius: .5rem; background: var(--color-grey-30); color: var(--color-font-primary); text-align: start; overflow: hidden; cursor: pointer; }
  .calendar-copy strong, .calendar-date-only strong { white-space: normal; max-width: 100%; min-width: 0; }
  .calendar-date-only button { min-width: 0; max-width: 100%; filter: none; box-shadow: none; }
  .calendar-date-only button.highlighted { border-left-color: var(--color-primary-start); background: color-mix(in srgb, var(--color-primary-start) 18%, var(--color-grey-20)); }
  .calendar-date-only span { font-size: .75rem; color: var(--color-font-secondary); }
  .calendar-item:disabled, .calendar-date-only button:disabled { cursor: default; opacity: 1; }
  .calendar-item.contextual, .calendar-date-only button.contextual { opacity: .48; border-left-style: dashed; }
  .calendar-empty { display: grid; min-height: 8rem; place-items: center; color: var(--color-font-secondary); }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .compact, .compact.date-only { height: 100%; min-height: 0; max-height: none; padding: 2px; gap: 2px; overflow: hidden; background: transparent; }
  .compact .calendar-week-toolbar { min-height: 20px; width: 100%; }
  .compact .calendar-week-toolbar strong { font-size: .625rem; }
  .compact .calendar-week { min-width: 0; width: 100%; grid-template-columns: 18px repeat(7, minmax(0, 1fr)); }
  .compact .calendar-week.date-only { grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .compact .calendar-day-header { min-height: 26px; gap: 0; flex-direction: column; font-size: .5625rem; line-height: 1.1; }
  .compact .calendar-time-column { font-size: .4375rem; }
  .compact .calendar-time-slots span { padding-right: 2px; }
  .compact .calendar-copy strong, .compact .calendar-date-only strong { font-size: .5625rem; line-height: 1.1; -webkit-line-clamp: 3; line-clamp: 3; }
  .compact .calendar-item { left: calc(100% * var(--calendar-item-column) / var(--calendar-item-columns) + 1px); width: calc(100% / var(--calendar-item-columns) - 2px); border-left-width: 2px; padding: 2px 1px; }
  .compact .calendar-date-only button { margin: 0 1px 4px; width: calc(100% - 2px); height: calc(var(--calendar-all-day-height) - 4px); border-left-width: 2px; padding: 3px 1px; border-radius: var(--radius-2); }
  @container (min-width: 400px) {
    .compact .calendar-week-toolbar strong { font-size: .75rem; }
    .compact .calendar-day-header { flex-direction: row; gap: .25rem; font-size: .75rem; }
    .compact .calendar-copy strong, .compact .calendar-date-only strong { font-size: .75rem; }
    .compact .calendar-time-column { font-size: .625rem; }
  }
</style>
