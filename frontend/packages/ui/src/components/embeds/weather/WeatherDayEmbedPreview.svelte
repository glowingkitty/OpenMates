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
    provider = 'Weather',
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

  let dayTitle = $derived(date || $text('apps.weather.day'));

  function formatTemp(min?: number, max?: number): string {
    if (min === undefined && max === undefined) return '—';
    if (min === undefined) return `${Math.round(max as number)}°`;
    if (max === undefined) return `${Math.round(min)}°`;
    return `${Math.round(min)}° / ${Math.round(max)}°`;
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
  showSkillIcon={false}
  customStatusText={provider ? `${$text('embeds.via')} ${provider}` : undefined}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="weather-day-details" class:mobile={isMobileLayout} data-testid="weather-day-preview">
      <div class="day-title" data-testid="weather-day-date">{date || $text('apps.weather.day')}</div>
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

<style>
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
