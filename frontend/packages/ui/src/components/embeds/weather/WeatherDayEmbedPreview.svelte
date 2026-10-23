<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedPreview.svelte

  Preview card for one weather_day child embed.
  Shows one day of weather while full hourly data remains in the stored embed content.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';
  import WeatherConditionIcon from './WeatherConditionIcon.svelte';
  import { text } from '@repo/ui';

  interface Props {
    id: string;
    date?: string;
    locationName?: string;
    provider?: string;
    condition?: string;
    icon?: string;
    temperatureMinC?: number;
    temperatureMaxC?: number;
    precipitationTotalMm?: number;
    precipitationProbabilityMaxPct?: number;
    rainHours?: number;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    date,
    locationName = '',
    icon = '',
    condition = '',
    temperatureMinC,
    temperatureMaxC,
    precipitationTotalMm,
    precipitationProbabilityMaxPct,
    rainHours,
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let dayTitle = $derived(formatDayTitle(date));
  let statusText = $derived(locationName);

  function formatTemp(min?: number, max?: number): string {
    if (min === undefined && max === undefined) return '—';
    if (min === undefined) return `${Math.round(max as number)}°`;
    if (max === undefined) return `${Math.round(min)}°`;
    return `${Math.round(min)}° / ${Math.round(max)}°`;
  }

  function formatDayTitle(value?: string): string {
    if (!value) return $text('apps.weather.day');
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'short', day: 'numeric' }).format(parsed);
  }

  function formatCondition(value?: string): string {
    if (!value) return '—';
    return value.replace(/[-_]/g, ' ');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="weather"
  skillId="weather_day"
  skillIconName="weather"
  {status}
  skillName={dayTitle}
  {taskId}
  {isMobile}
  {onFullscreen}
  resultPreview={true}
  showStatus={false}
  showSkillIcon={false}
  customStatusText={statusText || undefined}
>
  {#snippet details()}
    <div class="weather-day-result" data-testid="weather-day-preview">
      <ResultEmbedCard title={dayTitle} sourceLabel={statusText} description={condition ? formatCondition(condition) : undefined} media={icon || condition ? weatherMedia : undefined}>
        {#snippet badge()}{#if date}<EmbedCalendarDate {date} />{/if}{/snippet}
        {#snippet facts()}
          <span data-testid="weather-day-temperature">{formatTemp(temperatureMinC, temperatureMaxC)}</span>
          <span data-testid="weather-day-metrics" aria-label={$text('result_embed.rain_chance')}>{precipitationProbabilityMaxPct == null ? '—' : `${precipitationProbabilityMaxPct}%`}</span>
          <span class="weather-extra-metrics" data-testid="weather-day-extra-metrics">{precipitationTotalMm == null ? '—' : `${precipitationTotalMm} mm`} · {rainHours == null ? '—' : `${rainHours}h`}</span>
        {/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>
{#snippet weatherMedia()}<div class="weather-art" data-testid="weather-day-icon"><WeatherConditionIcon {icon} {condition} size="hero" /></div>{/snippet}
<style>
  .weather-extra-metrics { display: none; }
  @container result-card (min-width: 401px) { .weather-extra-metrics { display: inline; } }
  .weather-day-result { height:100%; width:100%; }
  .weather-art { display:grid; place-items:center; height:100%; width:100%; }
</style>
