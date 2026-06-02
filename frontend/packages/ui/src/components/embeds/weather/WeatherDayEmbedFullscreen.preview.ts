/** Preview mock data for WeatherDayEmbedFullscreen. */

export default {
  data: {
    decodedContent: {
      date: '2026-06-03',
      location_name: 'Berlin',
      provider: 'Deutscher Wetterdienst (DWD)',
      condition: 'rain',
      temperature_min_c: 14,
      temperature_max_c: 19,
      precipitation_total_mm: 5.8,
      precipitation_probability_max_pct: 67,
      rain_hours: 13,
      hourly: [
        { time: '06:00', temperature_c: 15, precipitation_mm: 0.2, precipitation_probability_pct: 31, wind_speed_kmh: 12 },
        { time: '07:00', temperature_c: 16, precipitation_mm: 0.4, precipitation_probability_pct: 48, wind_speed_kmh: 14 },
      ],
    },
    embedData: {},
  },
  onClose: () => console.log('[Preview] Close weather day fullscreen'),
};
