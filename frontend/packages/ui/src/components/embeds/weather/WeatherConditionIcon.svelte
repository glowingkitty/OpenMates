<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherConditionIcon.svelte

  Shared Meteocons-backed condition icon for weather embeds.
  Uses @meteocons/svg animated SVG assets instead of custom weather drawings.
-->

<script lang="ts">
  import clearDay from '@meteocons/svg/fill/clear-day.svg';
  import clearNight from '@meteocons/svg/fill/clear-night.svg';
  import cloudy from '@meteocons/svg/fill/cloudy.svg';
  import fogDay from '@meteocons/svg/fill/fog-day.svg';
  import overcast from '@meteocons/svg/fill/overcast.svg';
  import partlyCloudyDay from '@meteocons/svg/fill/partly-cloudy-day.svg';
  import partlyCloudyNight from '@meteocons/svg/fill/partly-cloudy-night.svg';
  import rain from '@meteocons/svg/fill/rain.svg';
  import snow from '@meteocons/svg/fill/snow.svg';
  import thunderstormsDayRain from '@meteocons/svg/fill/thunderstorms-day-rain.svg';
  import wind from '@meteocons/svg/fill/wind.svg';

  interface Props {
    icon?: string;
    condition?: string;
    label?: string;
    size?: 'sm' | 'md' | 'lg' | 'hero';
    decorative?: boolean;
  }

  const METEOCON_URLS = {
    'clear-day': clearDay,
    'clear-night': clearNight,
    cloudy,
    'fog-day': fogDay,
    overcast,
    'partly-cloudy-day': partlyCloudyDay,
    'partly-cloudy-night': partlyCloudyNight,
    rain,
    snow,
    'thunderstorms-day-rain': thunderstormsDayRain,
    wind,
  } as const;

  const WMO_PARTLY_CLOUDY_CODES = new Set([1, 2]);
  const WMO_OVERCAST_CODES = new Set([3]);
  const WMO_FOG_CODES = new Set([45, 48]);
  const WMO_DRIZZLE_RAIN_CODES = new Set([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]);
  const WMO_SNOW_CODES = new Set([71, 73, 75, 77, 85, 86]);
  const WMO_STORM_CODES = new Set([95, 96, 99]);

  type MeteoconSlug = keyof typeof METEOCON_URLS;

  let {
    icon = '',
    condition = '',
    label = 'Weather condition',
    size = 'md',
    decorative = true
  }: Props = $props();

  let iconSlug = $derived(resolveMeteoconSlug(icon, condition));
  let iconUrl = $derived(METEOCON_URLS[iconSlug]);
  let altText = $derived(decorative ? '' : label);

  function resolveMeteoconSlug(iconValue?: string, conditionValue?: string): MeteoconSlug {
    const normalized = `${iconValue ?? ''} ${conditionValue ?? ''}`.toLowerCase().replace(/_/g, '-');
    const wmoCode = normalized.match(/wmo-(\d+)/)?.[1];
    const numericWmoCode = wmoCode ? Number(wmoCode) : null;

    if (numericWmoCode !== null) {
      if (WMO_STORM_CODES.has(numericWmoCode)) return 'thunderstorms-day-rain';
      if (WMO_SNOW_CODES.has(numericWmoCode)) return 'snow';
      if (WMO_DRIZZLE_RAIN_CODES.has(numericWmoCode)) return 'rain';
      if (WMO_FOG_CODES.has(numericWmoCode)) return 'fog-day';
      if (WMO_OVERCAST_CODES.has(numericWmoCode)) return 'overcast';
      if (WMO_PARTLY_CLOUDY_CODES.has(numericWmoCode)) return 'partly-cloudy-day';
    }

    if (normalized.includes('thunder') || normalized.includes('storm') || normalized.includes('lightning')) {
      return 'thunderstorms-day-rain';
    }
    if (normalized.includes('snow') || normalized.includes('sleet') || normalized.includes('hail')) return 'snow';
    if (normalized.includes('rain') || normalized.includes('drizzle') || normalized.includes('shower')) return 'rain';
    if (normalized.includes('fog') || normalized.includes('mist') || normalized.includes('haze')) return 'fog-day';
    if (normalized.includes('wind')) return 'wind';
    if (normalized.includes('overcast')) return 'overcast';
    if (normalized.includes('cloud')) {
      if (normalized.includes('partly')) {
        return normalized.includes('night') || normalized.includes('moon') ? 'partly-cloudy-night' : 'partly-cloudy-day';
      }
      return 'cloudy';
    }
    if (normalized.includes('night') || normalized.includes('moon')) return 'clear-night';
    return 'clear-day';
  }
</script>

<span
  class="weather-condition-icon"
  class:sm={size === 'sm'}
  class:lg={size === 'lg'}
  class:hero={size === 'hero'}
  data-icon={iconSlug}
>
  <img src={iconUrl} alt={altText} aria-hidden={decorative ? true : undefined} loading="lazy" decoding="async" />
</span>

<style>
  .weather-condition-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 58px;
    height: 58px;
    flex: 0 0 auto;
    filter: drop-shadow(0 8px 18px color-mix(in srgb, var(--color-grey-100) 18%, transparent));
  }

  .weather-condition-icon.sm {
    width: 34px;
    height: 34px;
    filter: drop-shadow(0 4px 8px color-mix(in srgb, var(--color-grey-100) 14%, transparent));
  }

  .weather-condition-icon.lg {
    width: 82px;
    height: 82px;
  }

  .weather-condition-icon.hero {
    width: min(26vw, 142px);
    height: min(26vw, 142px);
  }

  img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }

  @media (prefers-reduced-motion: reduce) {
    img {
      animation-play-state: paused;
    }
  }
</style>
