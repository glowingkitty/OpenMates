<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte

  Preview card for a single event (child embed).
  Used inside EventsSearchEmbedFullscreen as clickable cards that open
  EventEmbedFullscreen via ChildEmbedOverlay drill-down.

  Shows event image on the right side (matching WebsiteEmbedPreview pattern)
  with text content (title, date, location, badges) on the left.

  Unlike EventsSearchEmbedPreview (the parent search result), this component:
  - Receives structured EventResult data directly from the parent (no embed store lookup)
  - Is NOT mounted by AppSkillUseRenderer — it's instantiated inline by the parent fullscreen
  - Has no cancellation logic (child event embeds are finished by the time they render)
  - Uses showStatus=false and showSkillIcon=false so cards are compact with no bottom bar

  Design mirrors WebsiteEmbedPreview.svelte image-right pattern.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';
  import { text } from '../../../i18n/translations';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  /**
   * A single event result from the events/search skill backend.
   * Passed in by EventsSearchEmbedFullscreen after transforming child embed content.
   */
  interface EventResult {
    /** Child embed ID */
    embed_id: string;
    id?: string;
    provider?: string;
    title?: string;
    description?: string;
    url?: string;
    date_start?: string;
    date_end?: string;
    timezone?: string;
    /** "PHYSICAL" or "ONLINE" */
    event_type?: string;
    venue?: {
      name?: string;
      address?: string;
      city?: string;
      state?: string;
      country?: string;
      lat?: number;
      lon?: number;
    };
    organizer?: {
      id?: string;
      name?: string;
      slug?: string;
    };
    rsvp_count?: number;
    is_paid?: boolean;
    fee?: {
      amount?: number;
      currency?: string;
    };
    image_url?: string | null;
    cover_url?: string | null;
  }

  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    /** Child embed ID used as UnifiedEmbedPreview id */
    id: string;
    /** Full structured event data */
    event: EventResult;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Optional localized labels for compact preview metadata. */
    onlineLabel?: string;
    inPersonLabel?: string;
    rsvpLabel?: string;
    /** Click handler that opens EventEmbedFullscreen drill-down */
    onFullscreen: () => void;
  }

  let {
    resultContext = 'auto',
    id,
    event,
    isMobile = false,
    onlineLabel: _onlineLabel = 'Online',
    inPersonLabel: _inPersonLabel = 'In Person',
    rsvpLabel = 'RSVPs',
    onFullscreen,
  }: Props = $props();

  let startTime = $derived.by(() => {
    if (!event.date_start) return '';
    const date = new Date(event.date_start);
    if (Number.isNaN(date.getTime())) return '';
    try { return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZone: event.timezone }); }
    catch { return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }); }
  });
  let attribution = $derived([startTime, event.organizer?.name ? `${$text('embeds.video_by')} ${event.organizer.name}` : ''].filter(Boolean).join(', '));

  let eventImageUrl = $derived.by(() => {
    const rawImageUrl = event.image_url || event.cover_url;
    return rawImageUrl ? proxyImage(rawImageUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : '';
  });



  // No-op stop handler — child event embeds are already finished
  async function handleStop() {
    // Not applicable for finished child event embeds
  }
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="events"
  skillId="event"
  skillIconName="event"
  status="finished"
  skillName={event.title || ''}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={!!eventImageUrl && !event.title}
>
  {#snippet details()}
    <ResultEmbedCard title={event.title || 'Event'} imageUrl={eventImageUrl || undefined} imageAlt={event.title || 'Event'} mediaFit="contain">
      {#snippet badge()}{#if event.date_start}<EmbedCalendarDate date={event.date_start} timezone={event.timezone} />{/if}{/snippet}
      {#snippet facts()}
        <div class="event-preview-facts">
          {#if attribution}<span class="event-preview-attribution" data-testid="event-preview-attribution" title={attribution}>{attribution}</span>{/if}
          {#if event.rsvp_count != null}<span class="event-preview-rsvps" data-testid="event-preview-rsvps"><span class="clickable-icon rsvp-icon" style:mask-image="var(--icon-url-team)" aria-hidden="true"></span><span>{event.rsvp_count.toLocaleString()} {rsvpLabel}</span></span>{/if}
        </div>
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .rsvp-icon { width: 16px; height: 16px; background: currentColor; cursor: inherit; }
  .event-preview-facts { display: flex; align-items: center; gap: var(--spacing-2); min-width: 0; width: 100%; color: var(--color-font-secondary); }
  .event-preview-attribution { display: block; flex: 1; min-width: 0; font-size: var(--font-size-xxs); line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .event-preview-rsvps { display: inline-flex; flex-shrink: 0; align-items: center; gap: var(--spacing-1); font-size: var(--font-size-xxs); line-height: 1.2; }
  @container result-card (min-width: 401px) { .event-preview-facts { flex-direction: column; align-items: flex-start; gap: var(--spacing-4); } .event-preview-attribution { flex: none; max-width: 100%; } }
</style>
