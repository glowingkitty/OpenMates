<!--
  LandingEventEmbed.svelte

  Self-contained event embed for the standalone website's "Actionable" story.
  The website cannot import the app's UI package, so this renders the event
  preview card and the expanded event view from the shared public result
  components (EventResultCard, EmbedPreviewCorner, EmbedCalendarDate), using the
  fixed demonstration event only. The app host passes the real event embed
  instead (see ui LandingExistingEmbed.svelte). Test ids match the real embed.
-->
<script lang="ts">
  import EventResultCard from '../results/EventResultCard.svelte';
  import EmbedPreviewCorner from '../results/EmbedPreviewCorner.svelte';
  import eventIcon from '../../assets/results/event.svg?url';
  import { featureAnimationCopy, landingAuthoredEvent as event } from './landingFeatureAnimationContent';

  type Props = { language: string } & (
    | { mode: 'preview'; activate: boolean; onFullscreen: () => void }
    | { mode: 'fullscreen' }
  );
  // This component is not a custom element.
  // svelte-ignore custom_element_props_identifier
  let props: Props = $props();
  let copy = $derived(featureAnimationCopy[props.language === 'de' ? 'de' : 'en']);
  let locale = $derived(props.language === 'de' ? 'de-DE' : 'en-US');
  // Date-only values are calendar days, not instants: format in UTC.
  let dateRange = $derived(new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' })
    .formatRange(new Date(`${event.dateStart}T00:00:00Z`), new Date(`${event.dateEnd}T00:00:00Z`)));
  let openLabel = $derived(copy.actionable_event_open.replace('{domain}', event.sourceDomain));
  let expandButton = $state<HTMLButtonElement>();

  $effect(() => {
    // The story clock presses the real expand control, like the app embed.
    if (props.mode === 'preview' && props.activate) expandButton?.click();
  });
</script>

{#if props.mode === 'preview'}
  <div class="event-preview-card" data-testid="embed-preview" data-app-id="events" data-skill-id="event">
    <EmbedPreviewCorner background="var(--color-app-events, var(--color-primary))" iconUrl={`url(${JSON.stringify(eventIcon)})`} />
    <EventResultCard title={event.title} date={event.dateStart} timezone="UTC" {locale} attribution={copy.actionable_event_city} />
    <button type="button" class="expand" bind:this={expandButton} data-testid="result-preview-expand" aria-label={copy.actionable_event_expand} onclick={props.onFullscreen} tabindex="-1">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
    </button>
  </div>
{:else}
  <div class="event-fullscreen" data-testid="landing-event-fullscreen">
    <div class="scroll">
      <div class="header">
        <h3 data-testid="event-fullscreen-title">{event.title}</h3>
        <p class="subtitle" data-testid="event-fullscreen-date">{dateRange}</p>
        <span class="cta" data-testid="external-provider-cta">{openLabel}</span>
      </div>
      <div class="facts">
        <span class="fact"><strong>{dateRange}</strong></span>
        <span class="fact"><strong>{copy.actionable_event_free}</strong></span>
      </div>
      <p class="description" data-testid="event-fullscreen-description">{copy.actionable_event_description}</p>
      <div class="venue" data-testid="event-venue-card"><small>{copy.actionable_event_at}</small><strong>{event.venueName}</strong><span>{event.venueCity}, {event.venueCountry}</span></div>
    </div>
  </div>
{/if}

<style>
  .event-preview-card { position: relative; container-type: inline-size; container-name: result-card; width: 100%; height: 200px; border-radius: 30px; overflow: hidden; background: var(--color-grey-0); box-shadow: 0 8px 24px rgb(0 0 0 / 16%), 0 2px 6px rgb(0 0 0 / 10%); }
  .expand { position: absolute; z-index: 3; right: 12px; bottom: 12px; width: 36px; height: 36px; display: grid; place-items: center; border: 0; border-radius: var(--radius-full); background: var(--color-grey-10); color: var(--color-font-primary); cursor: pointer; }
  .expand svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .event-fullscreen { width: 100%; height: 100%; overflow: hidden; border-radius: 30px; background: var(--color-grey-0); box-shadow: 0 8px 24px rgb(0 0 0 / 16%), 0 2px 6px rgb(0 0 0 / 10%); color: var(--color-font-primary); }
  .scroll { height: 100%; overflow: hidden; box-sizing: border-box; padding: 0 var(--spacing-10) var(--spacing-10); display: flex; flex-direction: column; gap: var(--spacing-6); text-align: center; }
  /* Banner in the events app colour, like the real event view's header. */
  .header { display: flex; flex-direction: column; align-items: center; gap: var(--spacing-3); margin-inline: calc(-1 * var(--spacing-10)); padding: var(--spacing-10) var(--spacing-10) var(--spacing-8); background: var(--color-app-events, var(--color-primary)); color: var(--color-font-button); }
  h3 { margin: 0; color: inherit; font-size: var(--font-size-h3); line-height: 1.2; font-weight: 700; }
  .subtitle { margin: 0; opacity: 0.9; font-size: var(--font-size-p); }
  .cta { margin-top: var(--spacing-3); display: inline-block; padding: var(--spacing-4) var(--spacing-10); border-radius: var(--radius-full); background: var(--color-button-primary, var(--color-primary)); color: var(--color-font-button); box-shadow: var(--shadow-md); font-weight: 700; font-size: var(--font-size-p); }
  .facts { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--spacing-6); }
  .description { margin: 0; line-height: 1.5; overflow-wrap: anywhere; }
  .venue { display: flex; flex-direction: column; gap: var(--spacing-1); padding: var(--spacing-6); border-radius: var(--radius-5, 20px); background: var(--color-grey-10); }
  .venue small { color: var(--color-font-tertiary); font-size: var(--font-size-xs); }
  .venue span { color: var(--color-font-secondary); }
</style>
