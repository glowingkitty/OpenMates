<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherConditionIcon.svelte

  Shared animated SVG condition icon for weather embeds.
  Keeps weather visuals local to the UI package without a runtime animation dependency.
-->

<script lang="ts">
  interface Props {
    icon?: string;
    condition?: string;
    label?: string;
    size?: 'sm' | 'md' | 'lg' | 'hero';
    decorative?: boolean;
  }

  let {
    icon = '',
    condition = '',
    label = 'Weather condition',
    size = 'md',
    decorative = true
  }: Props = $props();

  type WeatherKind = 'clear-day' | 'clear-night' | 'partly-cloudy' | 'cloudy' | 'rain' | 'snow' | 'storm' | 'fog' | 'wind';

  let kind = $derived(resolveWeatherKind(icon, condition));

  function resolveWeatherKind(iconValue?: string, conditionValue?: string): WeatherKind {
    const normalized = `${iconValue ?? ''} ${conditionValue ?? ''}`.toLowerCase().replace(/_/g, '-');

    if (normalized.includes('thunder') || normalized.includes('storm') || normalized.includes('lightning')) return 'storm';
    if (normalized.includes('snow') || normalized.includes('sleet') || normalized.includes('hail')) return 'snow';
    if (normalized.includes('rain') || normalized.includes('drizzle') || normalized.includes('shower')) return 'rain';
    if (normalized.includes('fog') || normalized.includes('mist') || normalized.includes('haze')) return 'fog';
    if (normalized.includes('wind')) return 'wind';
    if (normalized.includes('night') || normalized.includes('moon')) return 'clear-night';
    if (normalized.includes('cloud') || normalized.includes('overcast')) {
      return normalized.includes('partly') ? 'partly-cloudy' : 'cloudy';
    }
    return 'clear-day';
  }
</script>

<span
  class="weather-condition-icon"
  class:sm={size === 'sm'}
  class:lg={size === 'lg'}
  class:hero={size === 'hero'}
  data-kind={kind}
  aria-hidden={decorative ? true : undefined}
  aria-label={decorative ? undefined : label}
  role={decorative ? undefined : 'img'}
>
  <svg viewBox="0 0 120 120" focusable="false">
    {#if kind === 'clear-night'}
      <circle class="moon" cx="58" cy="48" r="26" />
      <circle class="moon-cutout" cx="70" cy="38" r="25" />
      <circle class="star star-a" cx="88" cy="28" r="3" />
      <circle class="star star-b" cx="28" cy="39" r="2.5" />
    {:else}
      <g class="sun-wrap">
        <circle class="sun" cx="46" cy="42" r="22" />
        <g class="rays">
          <path d="M46 9v13" />
          <path d="M46 62v13" />
          <path d="M13 42h13" />
          <path d="M66 42h13" />
          <path d="M22.7 18.7l9.2 9.2" />
          <path d="M60.1 56.1l9.2 9.2" />
          <path d="M69.3 18.7l-9.2 9.2" />
          <path d="M31.9 56.1l-9.2 9.2" />
        </g>
      </g>
    {/if}

    {#if kind === 'partly-cloudy' || kind === 'cloudy' || kind === 'rain' || kind === 'snow' || kind === 'storm' || kind === 'fog' || kind === 'wind'}
      <g class="cloud">
        <ellipse cx="61" cy="62" rx="34" ry="21" />
        <circle cx="40" cy="63" r="18" />
        <circle cx="58" cy="51" r="23" />
        <circle cx="82" cy="62" r="17" />
      </g>
    {/if}

    {#if kind === 'rain' || kind === 'storm'}
      <g class="rain-drops">
        <path d="M41 84l-7 17" />
        <path d="M61 84l-7 17" />
        <path d="M81 84l-7 17" />
      </g>
    {/if}

    {#if kind === 'snow'}
      <g class="snowflakes">
        <path d="M42 85v16M34 93h16M36.5 87.5l11 11M47.5 87.5l-11 11" />
        <path d="M72 85v16M64 93h16M66.5 87.5l11 11M77.5 87.5l-11 11" />
      </g>
    {/if}

    {#if kind === 'storm'}
      <path class="bolt" d="M65 73h17L68 102l3-20H56l13-29z" />
    {/if}

    {#if kind === 'fog'}
      <g class="fog-lines">
        <path d="M24 84h72" />
        <path d="M16 98h84" />
      </g>
    {/if}

    {#if kind === 'wind'}
      <g class="wind-lines">
        <path d="M22 50h51c10 0 10-14 0-14-5 0-8 3-9 7" />
        <path d="M18 68h70c12 0 12 17 0 17-6 0-10-4-11-9" />
        <path d="M31 86h32" />
      </g>
    {/if}
  </svg>
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

  svg {
    width: 100%;
    height: 100%;
    overflow: visible;
  }

  .sun {
    fill: #ffc857;
  }

  .sun-wrap {
    transform-origin: 46px 42px;
    animation: weather-sun-float 5s ease-in-out infinite;
  }

  .rays {
    stroke: #ffb627;
    stroke-width: 6;
    stroke-linecap: round;
    transform-origin: 46px 42px;
    animation: weather-rays-spin 18s linear infinite;
  }

  .moon {
    fill: #f7e9a0;
  }

  .moon-cutout {
    fill: var(--color-grey-0);
  }

  .star {
    fill: #f7e9a0;
    animation: weather-star-pulse 2.8s ease-in-out infinite;
  }

  .star-b {
    animation-delay: 0.9s;
  }

  .cloud {
    fill: #f7fbff;
    stroke: #d6e4f0;
    stroke-width: 2;
    transform-origin: 60px 62px;
    animation: weather-cloud-drift 4.5s ease-in-out infinite;
  }

  [data-kind='cloudy'] .cloud,
  [data-kind='fog'] .cloud,
  [data-kind='wind'] .cloud {
    fill: #e7eef6;
    stroke: #c7d4df;
  }

  .rain-drops {
    stroke: #4ba3ff;
    stroke-width: 7;
    stroke-linecap: round;
    animation: weather-rain-fall 1.1s linear infinite;
  }

  .snowflakes {
    stroke: #dff7ff;
    stroke-width: 4;
    stroke-linecap: round;
    animation: weather-snow-fall 2.8s ease-in-out infinite;
  }

  .bolt {
    fill: #ffd166;
    stroke: #ff9f1c;
    stroke-width: 2;
    animation: weather-bolt-flash 2.2s ease-in-out infinite;
  }

  .fog-lines,
  .wind-lines {
    fill: none;
    stroke: #a5b6c8;
    stroke-width: 6;
    stroke-linecap: round;
    animation: weather-wind-slide 3.4s ease-in-out infinite;
  }

  .wind-lines {
    stroke: #8eb6d8;
  }

  @keyframes weather-sun-float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-3px); }
  }

  @keyframes weather-rays-spin {
    to { transform: rotate(360deg); }
  }

  @keyframes weather-star-pulse {
    0%, 100% { opacity: 0.55; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.25); }
  }

  @keyframes weather-cloud-drift {
    0%, 100% { transform: translateX(0); }
    50% { transform: translateX(5px); }
  }

  @keyframes weather-rain-fall {
    0% { opacity: 0; transform: translateY(-8px); }
    20% { opacity: 1; }
    100% { opacity: 0; transform: translateY(12px); }
  }

  @keyframes weather-snow-fall {
    0%, 100% { transform: translateY(-3px) rotate(0deg); }
    50% { transform: translateY(5px) rotate(8deg); }
  }

  @keyframes weather-bolt-flash {
    0%, 68%, 100% { opacity: 0.8; }
    72%, 82% { opacity: 1; filter: brightness(1.3); }
  }

  @keyframes weather-wind-slide {
    0%, 100% { opacity: 0.68; transform: translateX(-4px); }
    50% { opacity: 1; transform: translateX(5px); }
  }

  @media (prefers-reduced-motion: reduce) {
    .sun-wrap,
    .rays,
    .star,
    .cloud,
    .rain-drops,
    .snowflakes,
    .bolt,
    .fog-lines,
    .wind-lines {
      animation: none;
    }
  }
</style>
