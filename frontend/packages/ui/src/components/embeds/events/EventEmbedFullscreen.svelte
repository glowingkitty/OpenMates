<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte

  Fullscreen detail view for a single event (child embed drill-down).
  Uses ResultEmbedFullscreen for responsive map + detail card layout.

  Shows map when venue has lat/lon coordinates (physical events).
  Falls back to details-only layout when no coordinates (online events).

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { getContext } from 'svelte';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from '../../../types/authoredResult';
  import { formatEventResultDate, formatEventResultTime, isEventDateOnly, eventResultSourceDomain, eventResultSourceUrl, normalizeEventResult, validEventCoordinates, projectVisibleEventResult } from './eventResult';
  import { eventCalendarInput, downloadEventResultCalendarFile } from './eventCalendar';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { authStore } from '../../../stores/authStore';
  import { savedEmbedIds, loadEmbedSaved, toggleEmbedSaved, getEmbedIdFromContentRef } from '../../../services/savedEmbedService';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  const presentation = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);

  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Embed ID forwarded to UnifiedEmbedFullscreen for the share handler */
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // Build the event object from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both nested venue object (from search transformer) and flat TOON fields
  // (venue_lat, venue_lon, etc. — from _flatten_for_toon_tabular in embed_service.py).
  let dc = $derived(presentation?.presentationContent ?? presentation?.content ?? data.decodedContent);

  let event = $derived(normalizeEventResult(dc ?? {}, embedId || data.focusChildEmbedId || String(data.attrs?.id || data.embedData?.embed_id || '')));
  const calendarInput = $derived(eventCalendarInput(event));
  let followupResult = $derived(projectVisibleEventResult(event));

  function eventDate(value: string | undefined): Date | undefined {
    if (!value) return undefined;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
  }
  function dayKey(date: Date) {
    try { return date.toLocaleDateString('en-CA', { timeZone: event.timezone }); }
    catch { return date.toLocaleDateString('en-CA'); }
  }
  const timeRange = $derived.by(() => {
    const startTime = formatEventResultTime(event.date_start, event.timezone);
    if (!startTime) return '';
    const endTime = formatEventResultTime(event.date_end, event.timezone);
    if (!endTime) return startTime;
    const startDate = formatEventResultDate(event.date_start, event.timezone);
    const endDate = formatEventResultDate(event.date_end, event.timezone);
    return startDate === endDate ? `${startTime} – ${endTime}` : `${startDate} ${startTime} – ${endDate} ${endTime}`;
  });
  const dateLabel = $derived.by(() => {
    const startLabel = formatEventResultDate(event.date_start, event.timezone);
    if (!startLabel) return '';
    if (isEventDateOnly(event.date_start)) {
      const endLabel = formatEventResultDate(event.date_end, event.timezone);
      return endLabel && endLabel !== startLabel ? `${startLabel} – ${endLabel}` : startLabel;
    }
    // Keep established provider relative-date presentation. Authored records
    // retain their researched/supplied date instead of an aging 'upcoming' claim.
    if (!event.authoring) {
      const start = eventDate(event.date_start);
      if (start) {
        const now = new Date();
        if (dayKey(start) === dayKey(now)) return 'Today';
        if (dayKey(start) === dayKey(new Date(now.getTime() + 86400000))) return 'Tomorrow';
      }
    }
    return startLabel;
  });
  let headerTitle = $derived(event.title || '');
  let headerSubtitle = $derived(event.organizer?.name ? `${$text('embeds.video_by')} ${event.organizer.name}` : undefined);
  let isOnline = $derived(event.event_type === 'ONLINE' || event.online === true);
  let venueAddress = $derived([event.venue?.name, event.venue?.address, [event.venue?.city, event.venue?.state, event.venue?.country].filter(Boolean).join(', ')].filter(Boolean).join('\n'));

  // Provider descriptions can be Markdown or HTML. Convert only sanitized HTML;
  // the existing MarkdownContent renderer performs its own final sanitization.
  let descriptionMarkdown = $state('');
  function htmlDescriptionToMarkdown(safeHtml: string): string {
    const doc = new DOMParser().parseFromString(safeHtml, 'text/html');
    const escapeText = (value: string) => value.replace(/([\\`*_[\]<>])/g, '\\$1');
    const convert = (node: Node, depth = 0): string => {
      if (node.nodeType === Node.TEXT_NODE) return escapeText(node.textContent || '');
      if (!(node instanceof Element)) return '';
      const content = () => Array.from(node.childNodes).map(child => convert(child, depth)).join('');
      const tag = node.tagName.toLowerCase();
      if (tag === 'br') return '\n';
      if (tag === 'strong' || tag === 'b') return `**${content()}**`;
      if (tag === 'em' || tag === 'i') return `*${content()}*`;
      if (tag === 'a') { const href = node.getAttribute('href'); return href ? `[${content()}](<${href.replace(/>/g, '%3E')}>)` : content(); }
      if (tag === 'ul' || tag === 'ol') return '\n' + Array.from(node.children).filter(child => child.tagName === 'LI').map((child, index) => `${'  '.repeat(depth)}${tag === 'ol' ? `${index + 1}.` : '-'} ${Array.from(child.childNodes).map(item => convert(item, depth + 1)).join('').trim()}`).join('\n') + '\n';
      if (tag === 'p' || tag === 'div' || /^h[1-6]$/.test(tag)) return `\n\n${content()}\n\n`;
      if (tag === 'blockquote') return `\n\n> ${content().trim().replace(/\n/g, '\n> ')}\n\n`;
      return content();
    };
    return Array.from(doc.body.childNodes).map(node => convert(node)).join('').replace(/\n{3,}/g, '\n\n').trim();
  }
  $effect(() => {
    const description = event.description || '';
    let current = true;
    if (!/<\/?(?:p|br|div|ul|ol|li|strong|b|em|i|a|h[1-6])(?:\s|>)/i.test(description)) descriptionMarkdown = description;
    else {
      descriptionMarkdown = '';
      void import('dompurify').then(({ default: purifier }) => {
        const safe = purifier.sanitize(description, { ALLOWED_TAGS: ['p', 'div', 'br', 'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'a', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'], ALLOWED_ATTR: ['href', 'title'] });
        if (current) descriptionMarkdown = htmlDescriptionToMarkdown(safe);
      }).catch(() => { if (current) descriptionMarkdown = description.replace(/<[^>]*>/g, ''); });
    }
    return () => { current = false; };
  });

  // Map data — only when venue has coordinates
  let mapCenter = $derived(
    !isOnline ? validEventCoordinates(event.venue?.lat, event.venue?.lon) : undefined
  );

  let mapMarkers = $derived(
    mapCenter
      ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: event.venue?.name || event.title }]
      : []
  );

  let feeDisplay = $derived.by(() => {
    if (!event.fee) return '';
    const amount = event.fee.amount;
    const currency = event.fee.currency || '';
    if (amount == null) return '';
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch { return [currency, String(amount)].filter(Boolean).join(' '); }
  });



  let providerLabel  = $derived(event.provider || '');
  const sourceUrl = $derived(eventResultSourceUrl(event.url));
  let failedEventImage = $state<string>();
  let eventImageUrl = $derived.by(() => {
    const rawImageUrl = event.image_url || event.cover_url;
    const image = rawImageUrl ? proxyImage(rawImageUrl, MAX_WIDTH_HEADER_IMAGE) : '';
    return image && image !== failedEventImage ? image : '';
  });
  let openButtonText = $derived.by(() => {
    if (!sourceUrl) return '';
    if (providerLabel) return $text('embeds.open_on_provider').replace('{provider}', providerLabel);
    const domain = eventResultSourceDomain(sourceUrl);
    return domain ? $text('embeds.authoring.open_domain').replace('{domain}', domain)
      : $text('embeds.authoring.open_source');
  });

  function handleOpenEvent() {
    if (sourceUrl) window.open(sourceUrl, '_blank', 'noopener,noreferrer');
  }


  // Save / Saved: encrypted `saved` flag on the embed itself (no memory entry).
  const savedTargetId = $derived(embedId || data.focusChildEmbedId || getEmbedIdFromContentRef(data.attrs?.contentRef));
  let isSaved = $derived($savedEmbedIds.has(savedTargetId));
  $effect(() => { if (savedTargetId) void loadEmbedSaved(savedTargetId); });

  function handleToggleSaved() {
    if (savedTargetId) void toggleEmbedSaved(savedTargetId);
  }


  function handleAddToCalendar() {
    if (calendarInput) downloadEventResultCalendarFile(event);
  }

</script>

  {#snippet resultMedia()}
    {#if eventImageUrl}
      <img class="event-image" src={eventImageUrl} alt={event.title || 'Event'} loading="lazy" onerror={() => failedEventImage = eventImageUrl} />
    {/if}
  {/snippet}
<ResultEmbedFullscreen
  media={eventImageUrl ? resultMedia : undefined}
  result={followupResult}
  authoring={event.authoring}
  authoringPlacement="bottom"
  appId="events"
  skillId="event"
  {onClose}
  skillIconName="event"
  showShare={$authStore.isAuthenticated}
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {mapCenter}
  mapZoom={13}
  {mapMarkers}
  onCalendar={calendarInput ? handleAddToCalendar : undefined}
  currentEmbedId={embedId || event.embed_id}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      {#if $authStore.isAuthenticated}
        <EmbedHeaderCtaButton label={$text(isSaved ? 'embeds.saved_item' : 'embeds.save_item')} variant="secondary" iconName="heart" iconOnly pressed={isSaved} onclick={handleToggleSaved} testId="save-embed-cta" />
      {/if}
      {#if sourceUrl && openButtonText}
        <EmbedHeaderCtaButton label={openButtonText} href={event.authoring ? sourceUrl : undefined} onclick={event.authoring ? undefined : handleOpenEvent} testId="external-provider-cta" />
      {/if}
    </div>
  {/snippet}

  {#snippet summary()}
    <div class="event-facts" data-testid="event-facts" aria-label="Event facts">
      {#if event.is_paid === false || feeDisplay}<div class="event-fact"><span class="clickable-icon event-icon" style:width="20px" style:height="20px" style:mask-image="var(--icon-url-money)" aria-hidden="true"></span><strong>{event.is_paid === false ? $text('embeds.models3d.search.free') : feeDisplay}</strong></div>{/if}
      {#if timeRange || dateLabel}<div class="event-fact"><span class="clickable-icon event-icon" style:width="20px" style:height="20px" style:mask-image="var(--icon-url-calendar)" aria-hidden="true"></span><span>{#if timeRange}<strong data-testid="event-time-range">{timeRange}</strong><small data-testid="event-date-label">{dateLabel}</small>{:else}<strong data-testid="event-date-label">{dateLabel}</strong>{/if}</span></div>{/if}
      {#if event.rsvp_count != null}<div class="event-fact"><span class="clickable-icon event-icon" style:width="20px" style:height="20px" style:mask-image="var(--icon-url-team)" aria-hidden="true"></span><span><strong>{event.rsvp_count.toLocaleString()}</strong><small>{$text('guest_onboarding.landing_actionable_event_rsvps')}</small></span></div>{/if}
    </div>
  {/snippet}

  {#snippet identity()}
    <div class="event-identities" data-testid="event-identity-cards">
      {#if event.organizer?.name}<div class="event-identity" data-testid="event-organizer-card"><span class="clickable-icon event-icon" style:width="28px" style:height="28px" style:mask-image="var(--icon-url-user)" aria-hidden="true"></span><span><small>{$text('result_embed.event_organized_by')}</small><strong>{event.organizer.name}</strong></span></div>{/if}
      {#if isOnline || venueAddress}<div class="event-identity" data-testid="event-venue-card"><span class="clickable-icon event-icon" style:width="28px" style:height="28px" style:mask-image="var(--icon-url-maps)" aria-hidden="true"></span><span><small>{$text('result_embed.event_at')}</small>{#if isOnline}<strong>{$text('embeds.online_event')}</strong>{:else}<strong>{event.venue?.name || $text('common.location')}</strong><span class="venue-address">{[event.venue?.address, [event.venue?.city, event.venue?.state, event.venue?.country].filter(Boolean).join(', ')].filter(Boolean).join('\n')}</span>{/if}</span></div>{/if}
    </div>
  {/snippet}
  {#snippet detailContent()}
    {#if descriptionMarkdown}<div class="event-description" data-testid="event-description"><MarkdownContent content={descriptionMarkdown} /></div>{/if}
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .event-image { width: 100%; height: var(--result-media-height); min-height: 0; object-fit: contain; display: block; border-radius: var(--radius-5); background: var(--color-grey-90); }
  :global([data-theme="dark"]) .event-image { background: var(--color-grey-30); }
  .event-icon { background: currentColor; cursor: inherit; flex-shrink: 0; }
  .event-facts { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: var(--spacing-6); padding: var(--spacing-2); color: var(--color-font-secondary); }
  .event-fact { display: flex; align-items: center; gap: var(--spacing-2); font-size: var(--font-size-small); }
  .event-fact > span { display: flex; flex-direction: column; line-height: 1.25; }
  .event-fact small { font-size: var(--font-size-xxs); font-weight: 600; }
  .event-identities { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-3); width: 100%; margin-bottom: var(--spacing-8); }
  .event-identity { display: flex; align-items: center; justify-content: center; gap: var(--spacing-3); min-width: 0; padding: var(--spacing-4); border-radius: var(--radius-4); background: var(--color-grey-0); font-size: var(--font-size-small); }
  .event-identity:only-child { grid-column: 1 / -1; }
  .event-identity > span { min-width: 0; display: flex; flex-direction: column; overflow-wrap: anywhere; }
  .event-identity small { color: var(--color-font-secondary); font-size: var(--font-size-xxs); }
  .event-identity strong { color: var(--color-primary-start); }
  .event-identity[data-testid="event-venue-card"] .event-icon { color: var(--color-app-events-start); }
  .venue-address { white-space: pre-line; line-height: 1.35; font-size: var(--font-size-xxs); }
  .event-description { line-height: 1.5; }
</style>
