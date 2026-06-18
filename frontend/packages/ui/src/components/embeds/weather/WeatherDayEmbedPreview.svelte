<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedPreview.svelte

  Preview card for one weather_day child embed.
  Shows one day of weather while full hourly data remains in the stored embed content.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
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
    provider = 'Weather',
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
  let statusText = $derived([
    locationName,
    provider ? `${$text('embeds.via')} ${provider}` : ''
  ].filter(Boolean).join(' · '));

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
  showStatus={false}
  showSkillIcon={false}
  customStatusText={statusText || undefined}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="weather-day-details" class:mobile={isMobileLayout} data-testid="weather-day-preview">
      <div class="day-copy">
        <div class="day-title" data-testid="weather-day-date">{dayTitle}</div>
        <div class="day-condition" data-testid="weather-day-condition">{formatCondition(condition)}</div>
      </div>
      <div class="day-hero">
        <div data-testid="weather-day-icon">
          <WeatherConditionIcon {icon} {condition} size={isMobileLayout ? 'md' : 'lg'} />
        </div>
        <div class="day-temp" data-testid="weather-day-temperature">{formatTemp(temperatureMinC, temperatureMaxC)}</div>
      </div>
      <div class="day-metrics" data-testid="weather-day-metrics">
        <span>{precipitationProbabilityMaxPct ?? 0}% rain</span>
        <span>{precipitationTotalMm ?? 0} mm</span>
        <span>{rainHours ?? 0}h</span>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .weather-day-details {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 10px;
    height: 100%;
    min-height: 145px;
    padding: 12px;
    border-radius: 20px;
    background:
      radial-gradient(circle at 18% 18%, color-mix(in srgb, var(--color-app-weather) 28%, transparent), transparent 42%),
      linear-gradient(145deg, color-mix(in srgb, var(--color-app-weather) 14%, var(--color-grey-0)), var(--color-grey-0));
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 18%, var(--color-grey-20));
  }

  .weather-day-details.mobile {
    min-height: 132px;
    padding: 10px;
  }

  .day-copy {
    min-width: 0;
  }

  .day-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .day-title,
  .day-temp {
    color: var(--color-grey-100);
    font-weight: 600;
  }

  .day-title {
    font-size: 15px;
    line-height: 1.15;
  }

  .day-temp {
    font-size: 25px;
    line-height: 1;
    text-align: right;
    white-space: nowrap;
  }

  .day-condition,
  .day-metrics {
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .day-condition {
    margin-top: 3px;
    text-transform: capitalize;
  }

  .day-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .day-metrics span {
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-grey-0) 82%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 16%, var(--color-grey-20));
    padding: 4px 8px;
    box-shadow: 0 4px 14px color-mix(in srgb, var(--color-grey-100) 6%, transparent);
  }
</style>
