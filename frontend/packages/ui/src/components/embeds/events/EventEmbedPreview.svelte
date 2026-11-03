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
  import { getContext } from 'svelte';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from '../../../types/authoredResult';
  import { eventCalendarBadge, formatEventResultTime, normalizeEventResult, type EventResult } from './eventResult';

  const presentation = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);

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

  const sourceEvent = $derived(normalizeEventResult(presentation?.presentationContent ?? presentation?.content ?? event, id));
  const previewStatus = $derived(sourceEvent.authoring && ['processing', 'error', 'cancelled'].includes(String(sourceEvent.status))
    ? sourceEvent.status as 'processing' | 'error' | 'cancelled' : sourceEvent.title ? 'finished' : 'processing');
  const badge = $derived(eventCalendarBadge(sourceEvent.date_start, sourceEvent.timezone));
  const startTime = $derived(formatEventResultTime(sourceEvent.date_start, sourceEvent.timezone));
  const attribution = $derived([startTime, sourceEvent.organizer?.name ? `${$text('embeds.video_by')} ${sourceEvent.organizer.name}` : ''].filter(Boolean).join(', '));
  const eventImageUrl = $derived.by(() => {
    const rawImageUrl = sourceEvent.image_url || sourceEvent.cover_url;
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
  status={previewStatus}
  authoring={sourceEvent.authoring}
  skillName={sourceEvent.title || ''}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  hasFullWidthImage={!!eventImageUrl && !sourceEvent.title}
>
  {#snippet details()}
    <EventResultCard title={sourceEvent.title || $text('embeds.event')} imageUrl={eventImageUrl || undefined} date={badge.date} timezone={badge.timezone} {attribution} rsvpCount={sourceEvent.rsvp_count} {rsvpLabel} onImageError={handleImageError} />
  {/snippet}
</UnifiedEmbedPreview>
