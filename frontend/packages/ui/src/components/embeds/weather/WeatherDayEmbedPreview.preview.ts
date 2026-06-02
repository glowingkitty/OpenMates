/**
 * Preview mock data for WeatherDayEmbedPreview.
 * Access at: /dev/preview/embeds/weather/WeatherDayEmbedPreview
 */

const defaultProps = {
  id: 'preview-weather-day-1',
  date: '2026-06-03',
  locationName: 'Berlin',
  provider: 'Deutscher Wetterdienst (DWD)',
  condition: 'rain',
  temperatureMinC: 14,
  temperatureMaxC: 19,
  precipitationTotalMm: 5.8,
  precipitationProbabilityMaxPct: 67,
  rainHours: 13,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Weather day fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-weather-day-processing',
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-weather-day-error',
    status: 'error' as const,
  },
  cancelled: {
    ...defaultProps,
    id: 'preview-weather-day-cancelled',
    status: 'cancelled' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-weather-day-mobile',
    isMobile: true,
  },
};
