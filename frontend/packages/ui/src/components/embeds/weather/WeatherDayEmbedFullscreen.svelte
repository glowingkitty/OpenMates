<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedFullscreen.svelte

  Fullscreen detail view for one weather_day child embed.
  Shows the full hourly data stored in the child embed content.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  interface HourlyWeatherRow {
    time?: string;
    condition?: string;
    temperature_c?: number;
    precipitation_mm?: number;
    precipitation_probability_pct?: number;
    wind_speed_kmh?: number;
    cloud_cover_pct?: number;
    relative_humidity_pct?: number;
  }

  interface Props {
    data?: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let content = $derived(data?.decodedContent ?? {});
  let date = $derived(typeof content.date === 'string' ? content.date : '');
  let locationName = $derived(typeof content.location_name === 'string' ? content.location_name : '');
  let provider = $derived(typeof content.provider === 'string' ? content.provider : 'Weather');
  let hourly = $derived(Array.isArray(content.hourly) ? content.hourly as HourlyWeatherRow[] : []);
</script>

<UnifiedEmbedFullscreen
  appId="weather"
  skillId="weather_day"
  skillIconName="weather"
  showSkillIcon={true}
  embedHeaderTitle={date || $text('apps.weather.day')}
  embedHeaderSubtitle={[locationName, provider].filter(Boolean).join(' · ')}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="weather-day-fullscreen" data-testid="weather-day-fullscreen">
      <section class="summary-card" data-testid="weather-day-fullscreen-summary">
        <h3>{content.condition || $text('apps.weather.day')}</h3>
        <p>{content.temperature_min_c ?? '—'}° / {content.temperature_max_c ?? '—'}°</p>
        <p>{content.precipitation_total_mm ?? 0} mm · {content.precipitation_probability_max_pct ?? 0}% rain · {content.rain_hours ?? 0}h</p>
      </section>

      <section class="hourly-table" aria-label="Hourly weather forecast" data-testid="weather-hourly-table">
        {#each hourly as row}
          <div class="hour-row" data-testid="weather-hourly-row">
            <span class="hour-time">{row.time}</span>
            <span>{row.temperature_c ?? '—'}°</span>
            <span>{row.precipitation_mm ?? 0} mm</span>
            <span>{row.precipitation_probability_pct ?? 0}%</span>
            <span>{row.wind_speed_kmh ?? '—'} km/h</span>
          </div>
        {/each}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .weather-day-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px 16px 120px;
    max-width: 900px;
    margin: 0 auto;
  }

  .summary-card {
    border-radius: 18px;
    border: 1px solid var(--color-grey-20);
    background: var(--color-grey-0);
    padding: 18px;
  }

  .summary-card h3 {
    margin: 0 0 8px;
    color: var(--color-grey-100);
  }

  .summary-card p {
    margin: 4px 0;
    color: var(--color-grey-70);
  }

  .hourly-table {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--color-grey-20);
    border-radius: 18px;
    overflow: hidden;
  }

  .hour-row {
    display: grid;
    grid-template-columns: 70px repeat(4, minmax(0, 1fr));
    gap: 8px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--color-grey-10);
    color: var(--color-grey-80);
    font-size: 14px;
  }

  .hour-row:last-child {
    border-bottom: 0;
  }

  .hour-time {
    color: var(--color-grey-100);
    font-weight: 600;
  }

  @container fullscreen (max-width: 520px) {
    .hour-row {
      grid-template-columns: 52px repeat(2, minmax(0, 1fr));
    }

    .hour-row span:nth-child(4),
    .hour-row span:nth-child(5) {
      display: none;
    }
  }
</style>
