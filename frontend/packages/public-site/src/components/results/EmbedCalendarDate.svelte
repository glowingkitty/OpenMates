<!-- Shared calendar badge for dated embeds. Never infer a date when absent. -->
<script lang="ts">
  import EmbedTimePill from './EmbedTimePill.svelte';
  let { date, timezone, locale, timeLabel, size = 'compact' }: {
    date: string | Date;
    timezone?: string;
    locale?: string;
    timeLabel?: string;
    size?: 'compact' | 'large';
  } = $props();
  const dateText = $derived(typeof date === 'string' ? date.replace(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/, (_, day, month, year) => `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`) : date);
  const parsed = $derived(dateText instanceof Date ? dateText : new Date(dateText));
  const valid = $derived(!Number.isNaN(parsed.getTime()));
  const dateOptions = $derived.by(() => {
    // Provider timezone strings can be missing or invalid; retain a usable badge.
    const zone = timezone ?? (typeof dateText === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateText) ? 'UTC' : undefined);
    try { new Intl.DateTimeFormat(undefined, { timeZone: zone }); return { timeZone: zone }; }
    catch { return {}; }
  });
  const weekday = $derived(valid ? parsed.toLocaleDateString(locale, { ...dateOptions, weekday: 'short' }) : '');
  const day = $derived(valid ? parsed.toLocaleDateString(locale, { ...dateOptions, day: 'numeric' }) : '');
  const label = $derived(valid ? parsed.toLocaleDateString(locale, { ...dateOptions, dateStyle: 'full' }) : '');
</script>

{#if valid}
  <span class="calendar-identity">
  <time class="embed-calendar-date" class:large={size === 'large'} datetime={parsed.toISOString()} aria-label={label} data-testid="embed-calendar-date">
    <span>{weekday}</span>
    <strong>{day}</strong>
  </time>
  {#if timeLabel}<span class="calendar-time"><EmbedTimePill label={timeLabel} datetime={parsed.toISOString()} testId="embed-calendar-time" /></span>{/if}
  </span>
{/if}

<style>
  .calendar-identity { display: inline-flex; vertical-align: top; align-items: flex-start; gap: 6px; }
  .calendar-time { display: inline-flex; margin-top: 6px; --embed-time-pill-font-size: var(--embed-calendar-time-font-size, var(--font-size-xxs)); }
  .embed-calendar-date {
    display: inline-flex;
    flex: 0 0 auto;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 40px;
    box-sizing: border-box;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-xs);
    line-height: 1;
  }
  .embed-calendar-date > span { color: var(--color-error); font-size: .625rem; font-weight: 400; line-height: 1.15; }
  .embed-calendar-date > strong { font-size: 1.625rem; font-weight: 400; letter-spacing: -.06em; line-height: 1; }
  .large { width: 52px; height: 58px; border-radius: var(--radius-6); }
  .large span { font-size: var(--font-size-xxs); }
  .large strong { font-size: 2.25rem; }
  @container result-card (max-width: 199px) {
    .calendar-identity { flex-direction: column; gap: var(--spacing-2); }
    .calendar-time { margin-top: 0; }
  }
  @container result-card (min-width: 401px) {
    .calendar-identity { flex-direction: column; gap: var(--spacing-4); }
    .calendar-time { margin-top: 0; --embed-time-pill-font-size: var(--embed-calendar-time-font-size, var(--font-size-small)); }
    .embed-calendar-date { width: 52px; height: 58px; border-radius: var(--radius-6); }
    .embed-calendar-date > span { font-size: var(--font-size-xxs); }
    .embed-calendar-date > strong { font-size: 2.25rem; }
  }
</style>
