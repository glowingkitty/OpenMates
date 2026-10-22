<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedFullscreen.svelte

  Fullscreen detail view for one weather_day child embed.
  Shows the full hourly data stored in the child embed content.
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
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
  let precipitationTotalMm = $derived(typeof content.precipitation_total_mm === 'number' ? content.precipitation_total_mm : undefined);
  let precipitationProbabilityMaxPct = $derived(
    typeof content.precipitation_probability_max_pct === 'number' ? content.precipitation_probability_max_pct : undefined
  );
  let rainHours = $derived(typeof content.rain_hours === 'number' ? content.rain_hours : undefined);
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
  // The decoded envelope may include storage fields alongside forecast data.
  let visibleContext = $derived({
    date, location_name: locationName, provider, condition,
    temperature_min_c: temperatureMinC, temperature_max_c: temperatureMaxC,
    precipitation_total_mm: precipitationTotalMm, precipitation_probability_max_pct: precipitationProbabilityMaxPct,
    rain_hours: rainHours, wind_speed_max_kmh: windSpeedMaxKmh, cloud_cover_avg_pct: cloudCoverAvgPct,
    relative_humidity_avg_pct: humidityAvgPct,
    hourly: hourly.map((row) => ({
      time: typeof row.time === 'string' ? row.time : undefined,
      temperature_c: typeof row.temperature_c === 'number' ? row.temperature_c : undefined,
      precipitation_mm: typeof row.precipitation_mm === 'number' ? row.precipitation_mm : undefined,
      precipitation_probability_pct: typeof row.precipitation_probability_pct === 'number' ? row.precipitation_probability_pct : undefined,
      wind_speed_kmh: typeof row.wind_speed_kmh === 'number' ? row.wind_speed_kmh : undefined,
    })),
  });
</script>

<ResultEmbedFullscreen appId="weather" skillId="weather_day" skillIconName="weather" showSkillIcon={true}
  embedHeaderTitle={formattedDate} embedHeaderSubtitle={[locationName, provider].filter(Boolean).join(' · ')}
  result={visibleContext} {onClose} currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext} {navigateDirection} {showChatButton} {onShowChat}
>
  {#snippet summary()}
    <div class="weather-summary" data-testid="weather-day-fullscreen-summary">
      <ResultEmbedInfo icon="thermometer" label={$text('result_embed.temperature')} value={formatTemp(temperatureMinC, temperatureMaxC)}><p>{formatTemp(temperatureMinC, temperatureMaxC)}</p></ResultEmbedInfo>
      <ResultEmbedInfo icon="cloud-rain" label={$text('result_embed.rain_chance')} value={formatNumber(precipitationProbabilityMaxPct, '%')}>
        <p>{$text('result_embed.precipitation')}: {precipitationTotalMm == null ? '—' : `${precipitationTotalMm} mm`}</p>
        <p>{$text('result_embed.rain_hours')}: {rainHours == null ? '—' : `${rainHours}h`}</p>
      </ResultEmbedInfo>
      {#if windSpeedMaxKmh != null}<ResultEmbedInfo icon="wind" label={$text('result_embed.wind')} value={formatNumber(windSpeedMaxKmh, ' km/h')}><p>{formatNumber(windSpeedMaxKmh, ' km/h')}</p></ResultEmbedInfo>{/if}
    </div>
  {/snippet}
  {#snippet detailContent()}
    <div class="weather-day-fullscreen" data-testid="weather-day-fullscreen">
      <div class="weather-identity">
        {#if icon || condition}<WeatherConditionIcon {icon} {condition} size="hero" />{/if}
        {#if condition}<p class="result-description">{formatCondition(condition)}</p>{/if}
        {#if locationName}<div class="result-location">{locationName}</div>{/if}
      </div>
      <div class="result-icon-row">
        {#if precipitationTotalMm != null}<ResultEmbedInfo icon="droplets" label={$text('result_embed.precipitation')} value={`${precipitationTotalMm} mm`}><p>{precipitationTotalMm} mm</p></ResultEmbedInfo>{/if}
        {#if rainHours != null}<ResultEmbedInfo icon="clock" label={$text('result_embed.rain_hours')} value={`${rainHours}h`}><p>{rainHours}h</p></ResultEmbedInfo>{/if}
        {#if cloudCoverAvgPct != null}<ResultEmbedInfo icon="cloud" label={$text('result_embed.clouds')} value={formatNumber(cloudCoverAvgPct, '%')}><p>{formatNumber(cloudCoverAvgPct, '%')}</p></ResultEmbedInfo>{/if}
        {#if humidityAvgPct != null}<ResultEmbedInfo icon="droplet" label={$text('result_embed.humidity')} value={formatNumber(humidityAvgPct, '%')}><p>{formatNumber(humidityAvgPct, '%')}</p></ResultEmbedInfo>{/if}
      </div>
      <section class="hourly-card" aria-label={$text('result_embed.hourly_forecast')} data-testid="weather-hourly-table">
        <h3>{$text('result_embed.hourly_forecast')} ({hourly.length})</h3>
        {#if hourly.length > 0}<div class="hourly-strip">
          {#each hourly as row}<div class="hour-row" data-testid="weather-hourly-row">
            <span class="hour-time">{row.time}</span>
            <WeatherConditionIcon icon={row.icon || icon} condition={row.condition || condition} size="sm" />
            <strong>{row.temperature_c ?? '—'}°</strong>
            <span>{row.precipitation_probability_pct ?? '—'}%</span>
            <span>{row.precipitation_mm ?? '—'} mm</span>
            <span>{row.wind_speed_kmh ?? '—'} km/h</span>
          </div>{/each}
        </div>{:else}<p class="empty-hourly">{$text('result_embed.no_hourly_data')}</p>{/if}
      </section>
    </div>
  {/snippet}
</ResultEmbedFullscreen>
<style>
 .weather-summary, .weather-identity { display:flex; align-items:center; justify-content:center; gap:var(--spacing-4); flex-wrap:wrap; }
 .weather-day-fullscreen { width:100%; display:flex; flex-direction:column; gap:var(--spacing-8); }
 .weather-identity { flex-direction:column; text-align:center; }
 .hourly-card { width:100%; min-width:0; }
 h3 { font-size:var(--font-size-small); margin:0 0 var(--spacing-4); }
 .hourly-strip { display:flex; gap:var(--spacing-3); overflow-x:auto; padding-block:var(--spacing-2); }
 .hour-row { display:flex; flex:0 0 6rem; flex-direction:column; align-items:center; gap:var(--spacing-2); padding:var(--spacing-4); background:var(--color-grey-0); border-radius:var(--radius-4); font-size:var(--font-size-xs); }
 .hour-time { font-weight:600; }
 .empty-hourly { color:var(--color-font-secondary); font-size:var(--font-size-small); }
</style>
