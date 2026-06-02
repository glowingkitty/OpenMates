/**
 * App-store examples for the weather forecast skill.
 *
 * Captured from real forecast skill responses covering both supported provider
 * routes: Germany uses Bright Sky / DWD, while international locations use
 * Open-Meteo. The result shape matches WeatherForecastEmbedPreview and the
 * fullscreen's legacy results fallback.
 */

export interface WeatherForecastStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  locationName: string;
  location: {
    name: string;
    latitude: number;
    longitude: number;
    country_code?: string;
  };
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: WeatherForecastStoreExample[] = [
  {
    id: 'store-example-weather-forecast-berlin',
    query: 'Berlin weather forecast for this week',
    query_translation_key: 'settings.app_store_examples.weather.forecast.1',
    locationName: 'Berlin',
    location: {
      name: 'Berlin',
      latitude: 52.52,
      longitude: 13.405,
      country_code: 'DE',
    },
    provider: 'Bright Sky / DWD',
    status: 'finished',
    results: [
      {
        embed_id: 'store-example-weather-day-berlin-1',
        date: '2026-06-02',
        location_name: 'Berlin',
        provider: 'Bright Sky / DWD',
        condition: 'dry',
        temperature_min_c: 15,
        temperature_max_c: 26,
        precipitation_total_mm: 0,
        precipitation_probability_max_pct: 4,
        rain_hours: 0,
        wind_speed_max_kmh: 18,
      },
      {
        embed_id: 'store-example-weather-day-berlin-2',
        date: '2026-06-03',
        location_name: 'Berlin',
        provider: 'Bright Sky / DWD',
        condition: 'rain',
        temperature_min_c: 14,
        temperature_max_c: 19,
        precipitation_total_mm: 5.8,
        precipitation_probability_max_pct: 67,
        rain_hours: 13,
        wind_speed_max_kmh: 24,
      },
      {
        embed_id: 'store-example-weather-day-berlin-3',
        date: '2026-06-04',
        location_name: 'Berlin',
        provider: 'Bright Sky / DWD',
        condition: 'rain',
        temperature_min_c: 13,
        temperature_max_c: 21,
        precipitation_total_mm: 4.9,
        precipitation_probability_max_pct: 37,
        rain_hours: 9,
        wind_speed_max_kmh: 22,
      },
    ],
  },
  {
    id: 'store-example-weather-forecast-tokyo',
    query: 'Tokyo weather forecast for the next few days',
    query_translation_key: 'settings.app_store_examples.weather.forecast.2',
    locationName: 'Tokyo',
    location: {
      name: 'Tokyo',
      latitude: 35.6764,
      longitude: 139.65,
      country_code: 'JP',
    },
    provider: 'Open-Meteo',
    status: 'finished',
    results: [
      {
        embed_id: 'store-example-weather-day-tokyo-1',
        date: '2026-06-02',
        location_name: 'Tokyo',
        provider: 'Open-Meteo',
        condition: 'rain',
        temperature_min_c: 20,
        temperature_max_c: 25,
        precipitation_total_mm: 8.4,
        precipitation_probability_max_pct: 73,
        rain_hours: 11,
        wind_speed_max_kmh: 19,
      },
      {
        embed_id: 'store-example-weather-day-tokyo-2',
        date: '2026-06-03',
        location_name: 'Tokyo',
        provider: 'Open-Meteo',
        condition: 'cloudy',
        temperature_min_c: 21,
        temperature_max_c: 27,
        precipitation_total_mm: 1.2,
        precipitation_probability_max_pct: 34,
        rain_hours: 3,
        wind_speed_max_kmh: 17,
      },
      {
        embed_id: 'store-example-weather-day-tokyo-3',
        date: '2026-06-04',
        location_name: 'Tokyo',
        provider: 'Open-Meteo',
        condition: 'dry',
        temperature_min_c: 22,
        temperature_max_c: 29,
        precipitation_total_mm: 0,
        precipitation_probability_max_pct: 12,
        rain_hours: 0,
        wind_speed_max_kmh: 16,
      },
    ],
  },
];

export default examples;
