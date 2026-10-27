<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import ResultCalendarWeek from '@repo/public-site/components/results/ResultCalendarWeek.svelte';
  import { calendarEventWeekEntries, formatCalendarEventDate, isAllDayDate, normalizeCalendarEventContent } from '../../../utils/calendarEvent';
  import { downloadCalendarEventFile } from '../../../utils/calendarDownload';
  import { text } from '../../../i18n/translations';
  import { authStore } from '../../../stores/authStore';
  import type { EmbedFullscreenCommonProps, EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, embedId, onClose, hasPreviousEmbed, hasNextEmbed, onNavigatePrevious, onNavigateNext,
    navigateDirection, showChatButton, onShowChat }: Props = $props();
  let content = $derived(data.decodedContent);
  let document = $derived(normalizeCalendarEventContent(content));
  let event = $derived(document?.primary_event);
  let id = $derived(embedId || String(data.embedData?.embed_id || data.attrs?.id || ''));
  let ready = $derived(!!event && (!content.status || content.status === 'finished'));
  let entries = $derived(document ? calendarEventWeekEntries(document, id) : []);
  let exportError = $state(false);
  let labels = $derived({ week: $text('calendar_event.week'), previous: $text('calendar_event.previous'), next: $text('calendar_event.next'),
    primary: $text('calendar_event.primary'), context: $text('calendar_event.context'), empty: $text('calendar_event.unavailable') });
  let followup = $derived(event ? { ...event, context_events: document?.context_events.map(item => ({ title: item.title, start: item.start, end: item.end, timezone: item.timezone, location: item.location })) } : {});
  function exportEvent() { exportError = !ready || !downloadCalendarEventFile(id, content); }
  function ignore() { /* Context remains presentation-only. */ }
  $effect(() => { void id; void content; exportError = false; });
</script>

<ResultEmbedFullscreen result={followup} appId="calendar" skillId="event" skillIconName="calendar" appIconName="calendar"
  {onClose} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  {navigateDirection} {showChatButton} {onShowChat} currentEmbedId={id} showShare={$authStore.isAuthenticated}
  embedHeaderTitle={event?.title || $text('calendar_event.unavailable')}
  embedHeaderSubtitle={event ? formatCalendarEventDate(event) : ''} onCalendar={ready ? exportEvent : undefined}>
  {#snippet embedHeaderCta()}
    {#if ready}<EmbedHeaderCtaButton label={$text('calendar_event.add')} iconName="calendar" onclick={exportEvent} testId="calendar-event-fullscreen-add" />{/if}
  {/snippet}
  {#snippet summary()}
    {#if ready && event}
      <div class="event-facts" data-testid="calendar-event-facts">
        <ResultEmbedInfo icon="calendar" label={formatCalendarEventDate(event)} value={isAllDayDate(event.start) ? $text('calendar_event.all_day') : formatCalendarEventDate(event)} testId="calendar-event-date-info" />
        {#if event.location}<ResultEmbedInfo icon="map-pin" label={event.location} value={event.location} testId="calendar-event-location" />{/if}
      </div>
    {/if}
  {/snippet}
  {#snippet detailContent()}
    <div class="event-content" data-testid="calendar-event-fullscreen">
      {#if ready && event}
        {#if event.description}<div class="event-description" data-testid="calendar-event-description"><MarkdownContent content={event.description} /></div>{/if}
        {#if event.source_url}<a href={event.source_url} target="_blank" rel="noopener noreferrer" class="event-source" data-testid="calendar-event-source">{$text('calendar_event.source')}: {new URL(event.source_url).hostname}</a>{/if}
        {#if !isAllDayDate(event.start) && !event.end}<p class="end-unknown">{$text('calendar_event.end_unknown')}</p>{/if}
        <div class="event-calendar"><ResultCalendarWeek {entries} {labels} focusRef={id} compact interactive={false} onOpen={ignore} onHover={ignore} /></div>
      {:else}<p>{$text('calendar_event.unavailable')}</p>{/if}
      {#if exportError}<p class="export-error" role="alert">{$text('calendar_event.export_failed')}</p>{/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .event-facts { display: flex; justify-content: center; flex-wrap: wrap; gap: var(--spacing-6); max-width: 100%; }
  .event-content { width: 100%; min-width: 0; color: var(--color-font-primary); user-select: text; }
  .event-description { margin-bottom: var(--spacing-6); overflow-wrap: anywhere; }
  .event-source { display: inline-block; margin-bottom: var(--spacing-4); color: var(--color-primary); overflow-wrap: anywhere; }
  .event-source:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .event-calendar { height: 20rem; min-width: 0; margin-top: var(--spacing-6); container-type: inline-size; }
  .end-unknown { font-size: .875rem; color: var(--color-font-secondary); }
  .export-error { color: var(--color-error); font-size: .875rem; }
</style>
