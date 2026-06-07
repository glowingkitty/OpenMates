<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedFullscreen.svelte

  Fullscreen overview for Weather / Forecast skill embeds.
  Loads one child weather_day embed per requested forecast day.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import WeatherDayEmbedPreview from './WeatherDayEmbedPreview.svelte';
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
  skillIconName="search"
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
          <WeatherDayEmbedPreview
            id={day.embed_id}
            date={day.date}
            locationName={day.location_name || locationName}
            provider={day.provider || provider}
            condition={day.condition}
            icon={day.icon}
            temperatureMinC={day.temperature_min_c}
            temperatureMaxC={day.temperature_max_c}
            precipitationTotalMm={day.precipitation_total_mm}
            precipitationProbabilityMaxPct={day.precipitation_probability_max_pct}
            rainHours={day.rain_hours}
            status="finished"
            onFullscreen={() => openDay(index, days, day)}
          />
        {/each}
      </div>

      {#if selectedDayIndex >= 0 && loadedDays[selectedDayIndex]}
        <ChildEmbedOverlay>
          <WeatherDayEmbedFullscreen
            data={{ decodedContent: loadedDays[selectedDayIndex], embedData: {} }}
            onClose={closeDay}
            embedId={loadedDays[selectedDayIndex].embed_id}
            hasPreviousEmbed={selectedDayIndex > 0}
            hasNextEmbed={selectedDayIndex < loadedDays.length - 1}
            onNavigatePrevious={previousDay}
            onNavigateNext={nextDay}
          />
        </ChildEmbedOverlay>
      {/if}

    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

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

  @container fullscreen (max-width: 680px) {
    .forecast-grid {
      grid-template-columns: 1fr;
      max-width: 340px;
    }
  }
</style>
