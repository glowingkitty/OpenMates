<script lang="ts">
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';
  import EventEmbedFullscreen from '../embeds/events/EventEmbedFullscreen.svelte';
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
  // The real event embed with fixed demonstration data. provider is the event's
  // own domain, so the expanded view offers "Open on fosdem.org".
  let content = $derived({
    embed_id: 'landing-fosdem-event', id: 'landing-fosdem-event',
    provider: landingAuthoredEvent.sourceDomain,
    title: landingAuthoredEvent.title,
    description: copy.actionable_event_description,
    url: landingAuthoredEvent.sourceUrl,
    date_start: landingAuthoredEvent.dateStart,
    date_end: landingAuthoredEvent.dateEnd,
    timezone: 'UTC',
    event_type: 'PHYSICAL',
    venue: { name: landingAuthoredEvent.venueName, city: landingAuthoredEvent.venueCity, country: landingAuthoredEvent.venueCountry },
    is_paid: false,
  });

  $effect(() => {
    if (props.mode !== 'preview' || !props.activate || !host) return;
    // Drive the component's actual expand action and callback. The animation
    // only shows the fullscreen after that callback has opened it.
    host.querySelector<HTMLButtonElement>('[data-testid="result-preview-expand"]')?.click();
  });
  $effect(() => {
    if (props.mode !== 'fullscreen' || !host) return;
    const frame = host;
    const alignContent = () => {
      const area = frame.querySelector<HTMLElement>('.content-area');
      // Both beats keep the "Open on <domain>" button in view; it is the point of the expanded view.
      const target = frame.querySelector<HTMLElement>('[data-testid="external-provider-cta"]');
      const topBar = frame.querySelector<HTMLElement>('.embed-top-bar');
      const composer = frame.querySelector<HTMLElement>('[data-testid="embed-fixed-bottom"]');
      if (!area || !target || !topBar || !composer) return;
      const areaBounds = area.getBoundingClientRect();
      if (!areaBounds.height) return;
      const scale = areaBounds.height / area.clientHeight;
      const targetBounds = target.getBoundingClientRect();
      const scroll = Math.max(0, (targetBounds.bottom - composer.getBoundingClientRect().top) / scale + 12);
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
    <EventEmbedPreview id="landing-fosdem-event" event={content} resultContext="chat" onFullscreen={props.onFullscreen} />
  {:else}
    <EventEmbedFullscreen embedId="landing-fosdem-event" data={{ decodedContent: content }} onClose={() => { /* The story clock closes the demonstration. */ }} />
  {/if}
</div>
