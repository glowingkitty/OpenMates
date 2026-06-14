<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedFullscreen.svelte

  Fullscreen detail view for one weather_day child embed.
  Shows the full hourly data stored in the child embed content.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WeatherConditionIcon from './WeatherConditionIcon.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  interface HourlyWeatherRow {
    time?: string;
    condition?: string;
    icon?: string;
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

  let content = $derived.by(() => {
    const decodedContent = data?.decodedContent;
    return decodedContent && typeof decodedContent === 'object' ? decodedContent as Record<string, unknown> : {};
  });
  let date = $derived(typeof content.date === 'string' ? content.date : '');
  let locationName = $derived(typeof content.location_name === 'string' ? content.location_name : '');
  let provider = $derived(typeof content.provider === 'string' ? content.provider : 'Weather');
  let condition = $derived(typeof content.condition === 'string' ? content.condition : '');
  let icon = $derived(typeof content.icon === 'string' ? content.icon : '');
  let temperatureMinC = $derived(typeof content.temperature_min_c === 'number' ? content.temperature_min_c : undefined);
  let temperatureMaxC = $derived(typeof content.temperature_max_c === 'number' ? content.temperature_max_c : undefined);
  let precipitationTotalMm = $derived(typeof content.precipitation_total_mm === 'number' ? content.precipitation_total_mm : 0);
  let precipitationProbabilityMaxPct = $derived(
    typeof content.precipitation_probability_max_pct === 'number' ? content.precipitation_probability_max_pct : 0
  );
  let rainHours = $derived(typeof content.rain_hours === 'number' ? content.rain_hours : 0);
  let windSpeedMaxKmh = $derived(typeof content.wind_speed_max_kmh === 'number' ? content.wind_speed_max_kmh : undefined);
  let cloudCoverAvgPct = $derived(typeof content.cloud_cover_avg_pct === 'number' ? content.cloud_cover_avg_pct : undefined);
  let humidityAvgPct = $derived(typeof content.relative_humidity_avg_pct === 'number' ? content.relative_humidity_avg_pct : undefined);
  let hourly = $derived(Array.isArray(content.hourly) ? content.hourly as HourlyWeatherRow[] : []);
  let formattedDate = $derived(formatFullDate(date));

  function formatTemp(min?: number, max?: number): string {
    if (min === undefined && max === undefined) return '—';
    if (min === undefined) return `${Math.round(max as number)}°`;
    if (max === undefined) return `${Math.round(min)}°`;
    return `${Math.round(min)}° / ${Math.round(max)}°`;
  }

  function formatFullDate(value?: string): string {
    if (!value) return $text('apps.weather.day');
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(parsed);
  }

  function formatCondition(value?: string): string {
    if (!value) return $text('apps.weather.day');
    return value.replace(/[-_]/g, ' ');
  }

  function formatNumber(value?: number, suffix = ''): string {
    return value === undefined ? '—' : `${Math.round(value)}${suffix}`;
  }
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
        <div class="summary-copy">
          <p class="summary-kicker">{formattedDate}</p>
          <h3>{formatCondition(condition)}</h3>
          <p class="summary-location">{[locationName, provider].filter(Boolean).join(' · ')}</p>
          <p class="summary-temp">{formatTemp(temperatureMinC, temperatureMaxC)}</p>
        </div>
        <WeatherConditionIcon {icon} {condition} size="hero" />
      </section>

      <section class="metric-grid" aria-label="Weather summary metrics">
        <article class="metric-card">
          <span class="metric-label">Rain chance</span>
          <strong>{precipitationProbabilityMaxPct}%</strong>
          <span>{precipitationTotalMm} mm · {rainHours}h</span>
        </article>
        <article class="metric-card">
          <span class="metric-label">Wind</span>
          <strong>{formatNumber(windSpeedMaxKmh, ' km/h')}</strong>
          <span>Max speed</span>
        </article>
        <article class="metric-card">
          <span class="metric-label">Clouds</span>
          <strong>{formatNumber(cloudCoverAvgPct, '%')}</strong>
          <span>Average cover</span>
        </article>
        <article class="metric-card">
          <span class="metric-label">Humidity</span>
          <strong>{formatNumber(humidityAvgPct, '%')}</strong>
          <span>Average</span>
        </article>
      </section>

      <section class="hourly-card" aria-label="Hourly weather forecast" data-testid="weather-hourly-table">
        <div class="section-heading">
          <h4>Hourly forecast</h4>
          <span>{hourly.length} entries</span>
        </div>
        {#if hourly.length > 0}
          <div class="hourly-strip">
            {#each hourly as row}
              <div class="hour-row" data-testid="weather-hourly-row">
                <span class="hour-time">{row.time}</span>
                <WeatherConditionIcon icon={row.icon || icon} condition={row.condition || condition} size="sm" />
                <strong>{row.temperature_c ?? '—'}°</strong>
                <span>{row.precipitation_probability_pct ?? 0}% rain</span>
                <span>{row.precipitation_mm ?? 0} mm</span>
                <span>{row.wind_speed_kmh ?? '—'} km/h</span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="empty-hourly">No hourly data available.</p>
        {/if}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .weather-day-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 24px 16px 120px;
    max-width: 980px;
    margin: 0 auto;
  }

  .summary-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    min-height: 245px;
    border-radius: 32px;
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 24%, var(--color-grey-20));
    background:
      radial-gradient(circle at 88% 22%, color-mix(in srgb, var(--color-app-weather) 38%, transparent), transparent 34%),
      radial-gradient(circle at 10% 10%, color-mix(in srgb, #ffffff 72%, transparent), transparent 35%),
      linear-gradient(135deg, color-mix(in srgb, var(--color-app-weather) 28%, var(--color-grey-0)), var(--color-grey-0));
    box-shadow: 0 22px 55px color-mix(in srgb, var(--color-grey-100) 13%, transparent);
    padding: 28px;
    overflow: hidden;
  }

  .summary-copy {
    min-width: 0;
  }

  .summary-kicker,
  .summary-location {
    margin: 0;
    color: var(--color-grey-70);
    font-size: 14px;
  }

  .summary-card h3 {
    margin: 8px 0 0;
    color: var(--color-grey-100);
    font-size: clamp(30px, 5vw, 54px);
    line-height: 1;
    text-transform: capitalize;
  }

  .summary-temp {
    margin: 18px 0 0;
    color: var(--color-grey-100);
    font-size: clamp(34px, 6vw, 64px);
    font-weight: 700;
    line-height: 1;
  }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }

  .metric-card,
  .hourly-card {
    border-radius: 22px;
    border: 1px solid var(--color-grey-20);
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 12px 32px color-mix(in srgb, var(--color-grey-100) 7%, transparent);
  }

  .metric-card {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 16px;
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .metric-label {
    color: var(--color-grey-60);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .metric-card strong {
    color: var(--color-grey-100);
    font-size: 22px;
    line-height: 1.1;
  }

  .hourly-card {
    padding: 16px;
    overflow: hidden;
  }

  .section-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }

  .section-heading h4 {
    margin: 0;
    color: var(--color-grey-100);
    font-size: 17px;
  }

  .section-heading span,
  .empty-hourly {
    color: var(--color-grey-60);
    font-size: 13px;
  }

  .hourly-strip {
    display: flex;
    gap: 10px;
    overflow-x: auto;
    padding: 2px 2px 8px;
    scrollbar-width: thin;
  }

  .hour-row {
    display: flex;
    min-width: 96px;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    border-radius: 18px;
    background:
      radial-gradient(circle at 50% 15%, color-mix(in srgb, var(--color-app-weather) 18%, transparent), transparent 55%),
      var(--color-grey-10);
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 12%, var(--color-grey-20));
    color: var(--color-grey-70);
    font-size: 12px;
    padding: 11px 9px;
    text-align: center;
  }

  .hour-row strong,
  .hour-time {
    color: var(--color-grey-100);
  }

  .hour-row strong {
    font-size: 18px;
    line-height: 1;
  }

  .hour-time {
    font-weight: 600;
  }

  .empty-hourly {
    margin: 0;
  }

  @container fullscreen (max-width: 720px) {
    .summary-card {
      min-height: 220px;
      padding: 22px;
    }

    .metric-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @container fullscreen (max-width: 520px) {
    .weather-day-fullscreen {
      padding-inline: 10px;
    }

    .summary-card {
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
    }

    .metric-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
