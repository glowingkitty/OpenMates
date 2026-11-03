<script lang="ts">
  import CalendarEventEmbedPreview from '../embeds/calendar/CalendarEventEmbedPreview.svelte';
  import CalendarEventEmbedFullscreen from '../embeds/calendar/CalendarEventEmbedFullscreen.svelte';
  import { featureAnimationCopy, landingAuthoredEvent } from '@repo/public-site/components/landing/landingFeatureAnimationContent';

  type Props = { language: string } & (
    | { mode: 'preview'; activate: boolean; onFullscreen: () => void }
    | { mode: 'fullscreen'; showCalendar: boolean }
  );
  // This adapter is not a custom element.
  // svelte-ignore custom_element_props_identifier
  let props: Props = $props();
  let host = $state<HTMLDivElement>();
  let copy = $derived(featureAnimationCopy[props.language === 'de' ? 'de' : 'en']);
  let content = $derived({
    type: 'calendar_event', status: 'finished', schemaVersion: 1,
    primary_event: {
      title: landingAuthoredEvent.title,
      start: landingAuthoredEvent.dateStart,
      // Calendar's date-only end is exclusive: both 30 and 31 January appear.
      end: landingAuthoredEvent.calendarEndExclusive,
      location: copy.actionable_event_venue,
      description: copy.actionable_event_description,
      source_url: landingAuthoredEvent.sourceUrl,
    },
    context_events: [],
  });

  $effect(() => {
    if (props.mode !== 'preview' || !props.activate || !host) return;
    // Drive the component's actual expand action and callback. The animation
    // only shows the fullscreen after that callback has opened it.
    host.querySelector<HTMLButtonElement>('[data-testid="result-preview-expand"]')?.click();
  });
  $effect(() => {
    if (props.mode !== 'fullscreen' || !host) return;
    const showCalendar = props.showCalendar;
    const frame = host;
    const alignContent = () => {
      const area = frame.querySelector<HTMLElement>('.content-area');
      const target = frame.querySelector<HTMLElement>(showCalendar
        ? '[data-testid="embeds-results-view-calendar"]'
        : '[data-testid="calendar-event-fullscreen-add"]');
      const topBar = frame.querySelector<HTMLElement>('.embed-top-bar');
      const composer = frame.querySelector<HTMLElement>('[data-testid="embed-fixed-bottom"]');
      if (!area || !target || !topBar || !composer) return;
      const areaBounds = area.getBoundingClientRect();
      if (!areaBounds.height) return;
      const scale = areaBounds.height / area.clientHeight;
      const targetBounds = target.getBoundingClientRect();
      const scroll = showCalendar
        ? (targetBounds.top - topBar.getBoundingClientRect().bottom) / scale - 8
        : Math.max(0, (targetBounds.bottom - composer.getBoundingClientRect().top) / scale + 12);
      // Use the same playback clock as the scene. The second beat scrolls the
      // actual fullscreen content; it is visible to every visitor and recording.
      // Native fullscreen entrance and composer layout settle after mount.
      // Converge smoothly without restarting a browser smooth-scroll each frame.
      area.scrollTop += Math.abs(scroll) < 1 ? scroll : scroll * 0.3;
    };
    let animationFrame = 0;
    const started = performance.now();
    const settle = (now: number) => {
      alignContent();
      if (now - started < 1000) animationFrame = requestAnimationFrame(settle);
    };
    // Bound adjustment to each beat's first second. The parent playback clock
    // owns beat changes; no permanent animation loop survives this adjustment.
    animationFrame = requestAnimationFrame(settle);
    return () => cancelAnimationFrame(animationFrame);
  });
</script>

<div bind:this={host}>
  {#if props.mode === 'preview'}
    <CalendarEventEmbedPreview id="landing-fosdem-calendar-event" {content} status="finished" resultContext="chat" presentationOnly onFullscreen={props.onFullscreen} />
  {:else}
    <CalendarEventEmbedFullscreen embedId="landing-fosdem-calendar-event" data={{ decodedContent: content }} onClose={() => { /* The story clock closes the demonstration. */ }} />
  {/if}
</div>
