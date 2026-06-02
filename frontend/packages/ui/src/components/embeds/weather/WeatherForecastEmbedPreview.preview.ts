/**
 * Preview mock data for WeatherForecastEmbedPreview.
 * Access at: /dev/preview/embeds/weather/WeatherForecastEmbedPreview
 */

const results = [
  {
    date: '2026-06-02',
    condition: 'dry',
    temperature_min_c: 15,
    temperature_max_c: 26,
    precipitation_total_mm: 0,
    precipitation_probability_max_pct: 4,
    rain_hours: 0,
  },
  {
    date: '2026-06-03',
    condition: 'rain',
    temperature_min_c: 14,
    temperature_max_c: 19,
    precipitation_total_mm: 5.8,
    precipitation_probability_max_pct: 67,
    rain_hours: 13,
  },
  {
    date: '2026-06-04',
    condition: 'rain',
    temperature_min_c: 13,
    temperature_max_c: 21,
    precipitation_total_mm: 4.9,
    precipitation_probability_max_pct: 37,
    rain_hours: 9,
  },
];

const defaultProps = {
  id: 'preview-weather-forecast-1',
  query: 'Berlin weather forecast',
  locationName: 'Berlin',
  provider: 'Bright Sky / DWD',
  status: 'finished' as const,
  results,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Weather forecast fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-weather-forecast-processing',
    status: 'processing' as const,
    results: [],
  },
  error: {
    ...defaultProps,
    id: 'preview-weather-forecast-error',
    status: 'error' as const,
    results: [],
  },
  cancelled: {
    ...defaultProps,
    id: 'preview-weather-forecast-cancelled',
    status: 'cancelled' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-weather-forecast-mobile',
    isMobile: true,
  },
};
