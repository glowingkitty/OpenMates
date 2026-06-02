<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedFullscreen.svelte

  Fullscreen overview for Weather / Forecast skill embeds.
  Loads one child weather_day embed per requested forecast day.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WeatherDayEmbedPreview from './WeatherDayEmbedPreview.svelte';
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
    }));
  }
</script>

<UnifiedEmbedFullscreen
  appId="weather"
  skillId="forecast"
  skillIconName="weather"
  embedHeaderTitle={locationName || $text('apps.weather.forecast')}
  embedHeaderSubtitle={provider}
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
>
  {#snippet content(ctx)}
    {@const days = (ctx.children.length > 0 ? ctx.children : transformLegacyResults(legacyResults)) as WeatherDayResult[]}

    {#if ctx.isLoadingChildren}
      <div class="state">{$text('embeds.loading')}</div>
    {:else if days.length === 0}
      <div class="state">{$text('embeds.no_results')}</div>
    {:else}
      <div class="forecast-grid" data-testid="weather-forecast-fullscreen-grid">
        {#each days as day}
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
            isMobile={false}
            onFullscreen={() => {}}
          />
        {/each}
      </div>
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
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    padding: 24px 16px 120px;
    max-width: 1000px;
    margin: 0 auto;
  }

  @container fullscreen (max-width: 520px) {
    .forecast-grid {
      grid-template-columns: 1fr;
      padding-inline: 12px;
    }
  }
</style>
