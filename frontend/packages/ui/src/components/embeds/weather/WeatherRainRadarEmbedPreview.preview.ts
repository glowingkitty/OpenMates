/**
 * Preview mock data for WeatherRainRadarEmbedPreview.
 * Access at: /dev/preview/embeds/weather/WeatherRainRadarEmbedPreview
 */

const timeline = [
  {
    frame_id: 'frame-0',
    timestamp: '2026-06-14T13:00:00Z',
    kind: 'past' as const,
    label: '-10 min',
    rain_at_location_mm_5min: 0.02,
    max_intensity: 'light',
    rain_area_pct: 12,
  },
  {
    frame_id: 'frame-1',
    timestamp: '2026-06-14T13:10:00Z',
    kind: 'forecast' as const,
    label: '+10 min',
    rain_at_location_mm_5min: 0.08,
    max_intensity: 'light',
    rain_area_pct: 18,
  },
];

const defaultProps = {
  id: 'preview-weather-rain-radar-1',
  query: 'Berlin rain radar',
  locationName: 'Berlin',
  provider: 'Deutscher Wetterdienst (DWD) via Bright Sky',
  status: 'finished' as const,
  summary: {
    rain_expected: true,
    in_10_min: 'Light rain visible near Berlin.',
    next_2_hours: 'Light rain appears in the radar timeline near Berlin.',
    peak_intensity: 'light',
    preview_frame_id: 'frame-1',
  },
  timeline,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Weather rain radar fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-weather-rain-radar-processing',
    status: 'processing' as const,
    timeline: [],
  },
  error: {
    ...defaultProps,
    id: 'preview-weather-rain-radar-error',
    status: 'error' as const,
    timeline: [],
  },
  unavailable: {
    ...defaultProps,
    id: 'preview-weather-rain-radar-unavailable',
    summary: {
      rain_expected: null,
      in_10_min: 'Rain radar is unavailable for this location in V1.',
      next_2_hours: 'Germany DWD rain radar is available in V1; global radar coverage is not supported yet.',
      peak_intensity: 'unknown',
      preview_frame_id: null,
    },
    timeline: [],
  },
  mobile: {
    ...defaultProps,
    id: 'preview-weather-rain-radar-mobile',
    isMobile: true,
  },
};
