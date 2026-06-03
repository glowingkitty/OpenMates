<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedFullscreen.svelte

  Fullscreen overview for Weather / Forecast skill embeds.
  Loads one child weather_day embed per requested forecast day.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import WeatherDayEmbedFullscreen from './WeatherDayEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  interface WeatherDayResult {
    embed_id: string;
    date?: string;
    location_name?: string;
    provider?: string;
    condition?: string;
    icon?: string;
    temperature_min_c?: number;
    temperature_max_c?: number;
    precipitation_total_mm?: number;
    precipitation_probability_max_pct?: number;
    rain_hours?: number;
    wind_speed_max_kmh?: number;
    hourly?: unknown[];
  }

  interface Props {
    data: EmbedFullscreenRawData;
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

  let locationName = $derived.by(() => {
    const location = data.decodedContent?.location as Record<string, unknown> | undefined;
    return typeof location?.name === 'string' ? location.name : '';
  });
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Weather');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let legacyResults = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : []);
  let selectedDayIndex = $state(-1);
  let loadedDays = $state<WeatherDayResult[]>([]);
  let selectedDay = $derived(selectedDayIndex >= 0 ? loadedDays[selectedDayIndex] ?? null : null);


  function transformToWeatherDay(embedId: string, content: Record<string, unknown>): WeatherDayResult {
    return {
      embed_id: embedId,
      date: content.date as string | undefined,
      location_name: content.location_name as string | undefined,
      provider: content.provider as string | undefined,
      condition: content.condition as string | undefined,
      icon: content.icon as string | undefined,
      temperature_min_c: content.temperature_min_c as number | undefined,
      temperature_max_c: content.temperature_max_c as number | undefined,
      precipitation_total_mm: content.precipitation_total_mm as number | undefined,
      precipitation_probability_max_pct: content.precipitation_probability_max_pct as number | undefined,
      rain_hours: content.rain_hours as number | undefined,
      wind_speed_max_kmh: content.wind_speed_max_kmh as number | undefined,
      hourly: Array.isArray(content.hourly) ? content.hourly : undefined,
    };
  }

  function transformLegacyResults(results: unknown[]): WeatherDayResult[] {
    return (results as Record<string, unknown>[]).map((result, index) => ({
      embed_id: `weather-day-${index}`,
      date: result.date as string | undefined,
      location_name: result.location_name as string | undefined,
      provider: result.provider as string | undefined,
      condition: result.condition as string | undefined,
      icon: result.icon as string | undefined,
      temperature_min_c: result.temperature_min_c as number | undefined,
      temperature_max_c: result.temperature_max_c as number | undefined,
      precipitation_total_mm: result.precipitation_total_mm as number | undefined,
      precipitation_probability_max_pct: result.precipitation_probability_max_pct as number | undefined,
      rain_hours: result.rain_hours as number | undefined,
      wind_speed_max_kmh: result.wind_speed_max_kmh as number | undefined,
      hourly: Array.isArray(result.hourly) ? result.hourly : undefined,
    }));
  }

  function getDays(children: unknown[]): WeatherDayResult[] {
    return (children.length > 0 ? children : transformLegacyResults(legacyResults)) as WeatherDayResult[];
  }

  function updateLoadedDays(days: WeatherDayResult[]): void {
    loadedDays = days;
  }

  $effect(() => {
    const hasEmbedIds =
      (typeof embedIds === 'string' && embedIds.trim().length > 0) ||
      (Array.isArray(embedIds) && embedIds.length > 0);
    if (hasEmbedIds) return;
    if (legacyResults.length === 0) return;
    updateLoadedDays(transformLegacyResults(legacyResults));
  });

  function openDay(index: number, days: WeatherDayResult[], day: WeatherDayResult): void {
    updateLoadedDays(days.length > 0 ? days : [day]);
    selectedDayIndex = index;
  }

  function handleDayPointerDown(event: PointerEvent, index: number, days: WeatherDayResult[], day: WeatherDayResult): void {
    event.stopPropagation();
    openDay(index, days, day);
  }

  function formatTemp(min?: number, max?: number): string {
    if (min === undefined && max === undefined) return '—';
    if (min === undefined) return `${Math.round(max as number)}°`;
    if (max === undefined) return `${Math.round(min)}°`;
    return `${Math.round(min)}° / ${Math.round(max)}°`;
  }

  function closeDay(): void {
    selectedDayIndex = -1;
  }

  function previousDay(): void {
    if (selectedDayIndex <= 0) return;
    selectedDayIndex -= 1;
  }

  function nextDay(): void {
    if (selectedDayIndex >= loadedDays.length - 1) return;
    selectedDayIndex += 1;
  }
</script>

<UnifiedEmbedFullscreen
  appId="weather"
  skillId="forecast"
  showSkillIcon={false}
  embedHeaderTitle={$text('apps.weather.forecast')}
  embedHeaderSubtitle={locationName ? `(${locationName})` : ''}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToWeatherDay}
  legacyResults={legacyResults}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  onChildrenLoaded={(children) => updateLoadedDays(children as WeatherDayResult[])}
>
  {#snippet content(ctx)}
    {@const days = getDays(ctx.children)}

    {#if ctx.isLoadingChildren}
      <div class="state">{$text('embeds.loading')}</div>
    {:else if days.length === 0}
      <div class="state">{$text('embeds.no_results')}</div>
    {:else}
      <div class="forecast-grid" data-testid="weather-forecast-fullscreen-grid" data-selected-day-index={selectedDayIndex}>
        {#each days as day, index}
          <button
            type="button"
            class="forecast-day-card"
            data-testid="embed-preview"
            data-app-id="weather"
            data-skill-id="weather_day"
            data-status="finished"
            aria-label={`${$text('apps.weather.day')}: ${day.date ?? index + 1}`}
            onpointerdown={(event) => handleDayPointerDown(event, index, days, day)}
            onclick={() => openDay(index, days, day)}
          >
            <div class="day-content" data-testid="weather-day-preview">
              <div class="day-title" data-testid="weather-day-date">{day.date || $text('apps.weather.day')}</div>
              <div class="day-temp" data-testid="weather-day-temperature">{formatTemp(day.temperature_min_c, day.temperature_max_c)}</div>
              <div class="day-condition" data-testid="weather-day-condition">{day.condition || '—'}</div>
              <div class="day-metrics" data-testid="weather-day-metrics">
                <span>{day.precipitation_total_mm ?? 0} mm</span>
                <span>{day.precipitation_probability_max_pct ?? 0}%</span>
                <span>{day.rain_hours ?? 0}h rain</span>
              </div>
            </div>
            <div class="day-info-bar">
              <div class="app-icon-circle weather" data-testid="app-icon-circle" data-app-icon="weather">
                <div class="icon_rounded weather"></div>
              </div>
              <div class="day-info-text">
                <div class="day-info-title">{day.date || $text('apps.weather.day')}</div>
                <div class="day-info-provider">{$text('embeds.via')} {day.provider || provider}</div>
              </div>
            </div>
          </button>
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

{#if selectedDay}
  <ChildEmbedOverlay>
    <WeatherDayEmbedFullscreen
      data={{ decodedContent: selectedDay, embedData: {} }}
      onClose={closeDay}
      embedId={selectedDay.embed_id}
      hasPreviousEmbed={selectedDayIndex > 0}
      hasNextEmbed={selectedDayIndex < loadedDays.length - 1}
      onNavigatePrevious={previousDay}
      onNavigateNext={nextDay}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  .state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
    color: var(--color-font-secondary);
  }

  .forecast-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: var(--spacing-8);
    width: calc(100% - 20px);
    max-width: 720px;
    padding: var(--spacing-12) var(--spacing-5) 120px;
    margin: 0 auto;
  }

  .forecast-day-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 190px;
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
    padding: 18px 0 0;
    border: 0;
    border-radius: 20px;
    background: var(--color-grey-20);
    box-shadow: 0 4px 14px color-mix(in srgb, var(--color-grey-100) 18%, transparent);
    color: inherit;
    cursor: pointer;
    overflow: hidden;
    text-align: left;
    transition: transform 120ms ease, box-shadow 120ms ease;
  }

  .forecast-day-card:hover,
  .forecast-day-card:focus-visible {
    transform: translateY(-1px);
    box-shadow: 0 6px 18px color-mix(in srgb, var(--color-grey-100) 22%, transparent);
    outline: none;
  }

  .day-content {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 0 18px 14px;
  }

  .day-title,
  .day-temp,
  .day-info-title {
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
  .day-metrics,
  .day-info-provider {
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

  .day-info-bar {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
    min-height: 61px;
    background: var(--color-grey-30);
    border-radius: 30px;
  }

  .app-icon-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-app-weather);
  }

  .app-icon-circle .icon_rounded {
    position: relative;
    bottom: auto;
    left: auto;
    width: 26px;
    height: 26px;
    background: transparent !important;
  }

  .app-icon-circle .icon_rounded.weather::after {
    background-image: url('@openmates/ui/static/icons/weather.svg');
  }

  .day-info-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .day-info-provider {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @container fullscreen (max-width: 680px) {
    .forecast-grid {
      grid-template-columns: 1fr;
      max-width: 340px;
    }
  }
</style>
