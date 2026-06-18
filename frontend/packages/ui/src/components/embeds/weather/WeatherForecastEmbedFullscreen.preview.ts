/** Preview mock data for WeatherForecastEmbedFullscreen. */

export default {
  data: {
    decodedContent: {
      provider: 'Deutscher Wetterdienst (DWD)',
      location: { name: 'Berlin' },
      results: [
        { date: '2026-06-02', location_name: 'Berlin', provider: 'Deutscher Wetterdienst (DWD)', condition: 'dry', icon: 'clear-day', temperature_min_c: 15, temperature_max_c: 26, precipitation_total_mm: 0, precipitation_probability_max_pct: 4, rain_hours: 0 },
        { date: '2026-06-03', location_name: 'Berlin', provider: 'Deutscher Wetterdienst (DWD)', condition: 'rain', icon: 'rain', temperature_min_c: 14, temperature_max_c: 19, precipitation_total_mm: 5.8, precipitation_probability_max_pct: 67, rain_hours: 13 },
        { date: '2026-06-04', location_name: 'Berlin', provider: 'Deutscher Wetterdienst (DWD)', condition: 'snow', icon: 'snow', temperature_min_c: -2, temperature_max_c: 3, precipitation_total_mm: 4.1, precipitation_probability_max_pct: 58, rain_hours: 7 },
      ],
    },
    embedData: {},
  },
  onClose: () => console.log('[Preview] Close weather forecast fullscreen'),
};
