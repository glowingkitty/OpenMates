<!-- Pure event result content used by the app and the public landing demo. -->
<script lang="ts">
  import ResultEmbedCard from './ResultEmbedCard.svelte';
  import EmbedCalendarDate from './EmbedCalendarDate.svelte';
  import teamIcon from '../../assets/results/team.svg?url';
  let { title, imageUrl, date, timezone, locale, attribution = '', rsvpCount, rsvpLabel = 'RSVPs', onImageError }: {
    title: string;
    imageUrl?: string;
    date?: string;
    timezone?: string;
    locale?: string;
    attribution?: string;
    rsvpCount?: number;
    rsvpLabel?: string;
    onImageError?: (image: HTMLImageElement) => void;
  } = $props();
</script>

<ResultEmbedCard {title} {imageUrl} imageAlt={title} mediaFit="contain" {onImageError}>
  {#snippet badge()}{#if date}<EmbedCalendarDate {date} {timezone} {locale} />{/if}{/snippet}
  {#snippet facts()}
    <div class="event-preview-facts">
      {#if attribution}<span class="event-preview-attribution" data-testid="event-preview-attribution" title={attribution}>{attribution}</span>{/if}
      {#if rsvpCount != null}<span class="event-preview-rsvps" data-testid="event-preview-rsvps"><span class="rsvp-icon" style:--event-team-icon={`url(${JSON.stringify(teamIcon)})`} aria-hidden="true"></span><span>{rsvpCount.toLocaleString(locale)} {rsvpLabel}</span></span>{/if}
    </div>
  {/snippet}
</ResultEmbedCard>

<style>
  .rsvp-icon { display: inline-block; flex: 0 0 16px; width: 16px; height: 16px; background: currentColor; mask: var(--event-team-icon) center / contain no-repeat; }
  .event-preview-facts { display: flex; align-items: center; gap: var(--spacing-2); min-width: 0; width: 100%; color: var(--color-font-secondary); }
  .event-preview-attribution { display: block; flex: 1; min-width: 0; font-size: var(--font-size-p); line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .event-preview-rsvps { display: none; flex-shrink: 0; align-items: center; gap: var(--spacing-1); font-size: var(--font-size-p); line-height: 1.2; }
  @container result-card (min-width: 401px) { .event-preview-facts { flex-direction: column; align-items: flex-start; gap: var(--spacing-4); } .event-preview-attribution { flex: none; max-width: 100%; } .event-preview-rsvps { display: inline-flex; } }
</style>
