<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedPreview.svelte

  Preview card for one weather_day child embed.
  Shows one day of weather while full hourly data remains in the stored embed content.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
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
    const weekday = new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(parsed);
    return `${weekday}, ${value}`;
  }

  function getConditionIcon(): string {
    if (icon) return icon;
    const normalized = condition.toLowerCase();
    if (normalized.includes('rain')) return '☔';
    if (normalized.includes('cloud')) return '☁';
    if (normalized.includes('snow')) return '❄';
    if (normalized.includes('storm')) return '⛈';
    return '☀';
  }

  function handlePointerUp(event: PointerEvent): void {
    if (event.button !== 0 || status !== 'finished') return;
    onFullscreen();
  }
</script>

<div class="weather-day-preview-wrapper" role="presentation" onpointerup={handlePointerUp}>
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
    showSkillIcon={false}
    customStatusText={statusText || undefined}
  >
    {#snippet details({ isMobile: isMobileLayout })}
      <div class="weather-day-details" class:mobile={isMobileLayout} data-testid="weather-day-preview">
        <div class="day-title" data-testid="weather-day-date">{dayTitle}</div>
        <div class="day-weather-icon" data-testid="weather-day-icon" aria-hidden="true">{getConditionIcon()}</div>
        <div class="day-temp" data-testid="weather-day-temperature">{formatTemp(temperatureMinC, temperatureMaxC)}</div>
        <div class="day-condition" data-testid="weather-day-condition">{condition || '—'}</div>
        <div class="day-metrics" data-testid="weather-day-metrics">
          <span>{precipitationTotalMm ?? 0} mm</span>
          <span>{precipitationProbabilityMaxPct ?? 0}%</span>
          <span>{rainHours ?? 0}h rain</span>
        </div>
      </div>
    {/snippet}
  </UnifiedEmbedPreview>
</div>

<style>
  .weather-day-preview-wrapper {
    display: block;
    width: 100%;
  }

  .weather-day-details {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 5px;
    height: 100%;
  }

  .weather-day-details.mobile {
    justify-content: flex-start;
  }

  .day-title,
  .day-temp {
    color: var(--color-grey-100);
    font-weight: 600;
  }

  .day-title {
    font-size: 15px;
  }

  .day-weather-icon {
    color: var(--color-grey-100);
    font-size: 30px;
    line-height: 1;
  }

  .day-temp {
    font-size: 24px;
  }

  .day-condition,
  .day-metrics {
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .day-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .day-metrics span {
    border-radius: 999px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
    padding: 3px 7px;
  }
</style>
