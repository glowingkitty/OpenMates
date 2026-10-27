<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte

  Preview card for a single event (child embed).
  Used inside EventsSearchEmbedFullscreen as clickable cards that open
  EventEmbedFullscreen via ChildEmbedOverlay drill-down.

  Shows event image on the right side (matching WebsiteEmbedPreview pattern)
  with text content (title, date, location, badges) on the left.

  Unlike EventsSearchEmbedPreview (the parent search result), this component:
  - Receives structured EventResult data from the parent and hydrates deferred references
    through UnifiedEmbedPreview's existing store recovery callback
  - Is NOT mounted by AppSkillUseRenderer — it's instantiated inline by the parent fullscreen
  - Has no cancellation logic (child event embeds are finished by the time they render)
  - Uses showStatus=false and showSkillIcon=false so cards are compact with no bottom bar

  Design mirrors WebsiteEmbedPreview.svelte image-right pattern.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import EventResultCard from '@repo/public-site/components/results/EventResultCard.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { text } from '../../../i18n/translations';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { normalizeEventResult } from './eventResult';

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

  // A persisted reply can mount before its encrypted event is readable. The
  // shared shell refetches on mount/updates; consume that data instead of
  // retaining the empty EventResult that the imperative renderer first supplied.
  function handleEmbedDataUpdated({ decodedContent }: { status: string; decodedContent: Record<string, unknown> }) {
    if (typeof decodedContent.title !== 'string' || !decodedContent.title.trim()) return;
    event = normalizeEventResult(decodedContent, id);
  }

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
  status={event.title ? 'finished' : 'processing'}
  skillName={event.title || ''}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  hasFullWidthImage={!!eventImageUrl && !event.title}
>
  {#snippet details()}
    <EventResultCard title={event.title || 'Event'} imageUrl={eventImageUrl || undefined} date={event.date_start} timezone={event.timezone} {attribution} rsvpCount={event.rsvp_count} {rsvpLabel} onImageError={handleImageError} />
  {/snippet}
</UnifiedEmbedPreview>
