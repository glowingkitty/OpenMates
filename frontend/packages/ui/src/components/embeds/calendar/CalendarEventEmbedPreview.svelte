<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultCalendarWeek from '@repo/public-site/components/results/ResultCalendarWeek.svelte';
  import { calendarEventWeekEntries, formatCalendarEventDate, isAllDayDate, normalizeCalendarEventContent } from '../../../utils/calendarEvent';
  import { downloadCalendarEventFile } from '../../../utils/calendarDownload';
  import { text } from '../../../i18n/translations';

  type Status = 'processing' | 'finished' | 'error' | 'cancelled';
  interface Props {
    id: string;
    content: Record<string, unknown>;
    status?: Status;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }
  let { id, content, status: statusProp = 'finished', resultContext = 'auto', onFullscreen }: Props = $props();
  let localContent = $state<Record<string, unknown>>({});
  let status = $state<Status>('processing');
  let exportError = $state(false);
  $effect(() => { localContent = content; status = statusProp; exportError = false; });
  let document = $derived(normalizeCalendarEventContent(localContent));
  let event = $derived(document?.primary_event);
  let ready = $derived(status === 'finished' && !!event);
  let entries = $derived(document ? calendarEventWeekEntries(document, id) : []);
  let labels = $derived({ week: $text('calendar_event.week'), previous: $text('calendar_event.previous'), next: $text('calendar_event.next'),
    primary: $text('calendar_event.primary'), context: $text('calendar_event.context'), empty: $text('calendar_event.unavailable') });

  function updated(data: { status: string; decodedContent: Record<string, unknown> }) {
    localContent = data.decodedContent;
    if (['processing', 'finished', 'error', 'cancelled'].includes(data.status)) status = data.status as Status;
  }
  function exportEvent(event: MouseEvent) {
    event.stopPropagation();
    exportError = !ready || !downloadCalendarEventFile(id, { ...localContent, status });
  }
  function ignore() { /* The miniature calendar presents context; shared controls own actions. */ }
</script>

<UnifiedEmbedPreview {id} resultPreview {resultContext} appId="calendar" skillId="event" skillIconName="calendar" appIconName="calendar"
  {status} skillName={event?.title || $text('calendar_event.unavailable')} {onFullscreen}
  showSkillIcon={false} showStatus={false} onEmbedDataUpdated={updated}>
  {#snippet resultPrimaryAction()}
    <button type="button" class="calendar-export" data-testid="calendar-event-add" aria-label={$text('calendar_event.add')}
      title={$text('calendar_event.add')} disabled={!ready} onclick={exportEvent}>
      <span class="clickable-icon" style:mask-image="var(--icon-url-calendar)" aria-hidden="true"></span>
    </button>
  {/snippet}
  {#snippet details()}
    <div class="calendar-event-card" data-testid="calendar-event-preview" data-status={status}>
      {#if ready && event}
        <div class="event-details" data-testid="calendar-event-details">
          <strong class="event-title" title={event.title}>{event.title}</strong>
          <span class="event-date" data-testid="calendar-event-date" title={formatCalendarEventDate(event)}>{formatCalendarEventDate(event, undefined, true)}</span>
          {#if isAllDayDate(event.start)}<span class="all-day">{$text('calendar_event.all_day')}</span>{/if}
        </div>
        <div class="event-week" data-testid="calendar-event-week"><ResultCalendarWeek {entries} {labels} focusRef={id} compact interactive={false} showNavigation={false} onOpen={ignore} onHover={ignore} /></div>
      {:else}<p class="event-unavailable" data-testid="calendar-event-unavailable">{$text(status === 'processing' ? 'calendar_event.preparing' : 'calendar_event.unavailable')}</p>{/if}
      {#if exportError}<span class="export-error" role="alert">{$text('calendar_event.export_failed')}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .calendar-event-card { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: .5rem; width: 100%; height: 100%; min-height: 0; box-sizing: border-box; padding: 3.25rem .75rem .75rem 1rem; color: var(--color-font-primary); user-select: text; }
  .event-details { display: flex; flex-direction: column; justify-content: center; gap: .25rem; min-width: 0; overflow: hidden; }
  .event-title, .event-date, .all-day { flex-shrink: 0; }
  .event-title { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; font-size: 1rem; font-weight: 600; line-height: 1.25; }
  .event-date { font-size: .875rem; line-height: 1.3; overflow-wrap: anywhere; }
  .all-day { font-size: .75rem; color: var(--color-font-secondary); }
  .event-week { min-width: 0; min-height: 0; height: 100%; container-type: inline-size; }
  .event-unavailable { grid-column: 1 / -1; align-self: center; margin: 0; color: var(--color-font-secondary); font-size: .875rem; }
  .calendar-export:disabled { opacity: .45; cursor: default; }
  .export-error { grid-column: 1 / -1; font-size: .75rem; color: var(--color-error); }
</style>
