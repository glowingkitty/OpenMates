/** Preview mock data for WeatherDayEmbedFullscreen. */

export default {
  data: {
    decodedContent: {
      date: '2026-06-03',
      location_name: 'Berlin',
      provider: 'Deutscher Wetterdienst (DWD)',
      condition: 'rain',
      icon: 'rain',
      temperature_min_c: 14,
      temperature_max_c: 19,
      precipitation_total_mm: 5.8,
      precipitation_probability_max_pct: 67,
      rain_hours: 13,
      wind_speed_max_kmh: 24,
      cloud_cover_avg_pct: 86,
      relative_humidity_avg_pct: 72,
      hourly: [
        { time: '06:00', condition: 'cloudy', icon: 'cloudy', temperature_c: 15, precipitation_mm: 0.2, precipitation_probability_pct: 31, wind_speed_kmh: 12 },
        { time: '07:00', condition: 'rain', icon: 'rain', temperature_c: 16, precipitation_mm: 0.4, precipitation_probability_pct: 48, wind_speed_kmh: 14 },
        { time: '08:00', condition: 'rain', icon: 'rain', temperature_c: 16, precipitation_mm: 0.8, precipitation_probability_pct: 67, wind_speed_kmh: 18 },
        { time: '09:00', condition: 'thunderstorm', icon: 'thunderstorms-day-rain', temperature_c: 17, precipitation_mm: 1.2, precipitation_probability_pct: 74, wind_speed_kmh: 24 },
        { time: '10:00', condition: 'cloudy', icon: 'cloudy', temperature_c: 18, precipitation_mm: 0.1, precipitation_probability_pct: 28, wind_speed_kmh: 16 },
      ],
    },
    embedData: {},
  },
  onClose: () => console.log('[Preview] Close weather day fullscreen'),
};
