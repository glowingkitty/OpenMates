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
  icon: 'rain',
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
  providerHidden: { ...defaultProps, provider: 'Fixture Provider Must Stay Fullscreen' },
  longCity: { ...defaultProps, locationName: 'A deliberately long city and regional district name' },
  missing: { ...defaultProps, date: undefined, locationName: '', condition: '', icon: '', temperatureMinC: undefined, temperatureMaxC: undefined, precipitationTotalMm: undefined, precipitationProbabilityMaxPct: undefined, rainHours: undefined },
  zero: { ...defaultProps, temperatureMinC: 0, temperatureMaxC: 0, precipitationTotalMm: 0, precipitationProbabilityMaxPct: 0, rainHours: 0 },
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
  sunny: {
    ...defaultProps,
    id: 'preview-weather-day-sunny',
    condition: 'dry',
    icon: 'clear-day',
    temperatureMinC: 18,
    temperatureMaxC: 29,
    precipitationTotalMm: 0,
    precipitationProbabilityMaxPct: 3,
    rainHours: 0,
  },
  snow: {
    ...defaultProps,
    id: 'preview-weather-day-snow',
    condition: 'snow',
    icon: 'snow',
    temperatureMinC: -4,
    temperatureMaxC: 1,
    precipitationTotalMm: 8.2,
    precipitationProbabilityMaxPct: 76,
    rainHours: 10,
  },
};
