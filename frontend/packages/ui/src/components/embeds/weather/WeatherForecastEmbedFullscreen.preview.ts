/** Preview mock data for WeatherForecastEmbedFullscreen. */

export default {
  data: {
    decodedContent: {
      provider: 'Bright Sky / DWD',
      location: { name: 'Berlin' },
      results: [
        { date: '2026-06-02', location_name: 'Berlin', provider: 'Bright Sky / DWD', condition: 'dry', temperature_min_c: 15, temperature_max_c: 26, precipitation_total_mm: 0, precipitation_probability_max_pct: 4, rain_hours: 0 },
        { date: '2026-06-03', location_name: 'Berlin', provider: 'Bright Sky / DWD', condition: 'rain', temperature_min_c: 14, temperature_max_c: 19, precipitation_total_mm: 5.8, precipitation_probability_max_pct: 67, rain_hours: 13 },
      ],
    },
    embedData: {},
  },
  onClose: () => console.log('[Preview] Close weather forecast fullscreen'),
};
