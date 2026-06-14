/** Preview mock data for WeatherRainRadarEmbedFullscreen. */

const timeline = Array.from({ length: 8 }, (_, index) => ({
  frame_id: `frame-${index}`,
  timestamp: new Date(Date.UTC(2026, 5, 14, 13, index * 5)).toISOString(),
  kind: index < 2 ? 'past' as const : index === 2 ? 'current' as const : 'forecast' as const,
  label: index < 2 ? `-${(2 - index) * 5} min` : index === 2 ? 'now' : `+${(index - 2) * 5} min`,
  rain_at_location_mm_5min: index < 3 ? 0.02 : 0.08,
  max_intensity: index > 5 ? 'moderate' : 'light',
  rain_area_pct: 10 + index * 4,
}));

export default {
  embedId: 'preview-weather-rain-radar-fullscreen',
  data: {
    decodedContent: {
      type: 'rain_radar',
      provider: 'Deutscher Wetterdienst (DWD) via Bright Sky',
      location: {
        name: 'Berlin',
        country_code: 'DE',
        latitude: 52.52,
        longitude: 13.405,
      },
      coverage: { status: 'available', radius_km: 5 },
      summary: {
        rain_expected: true,
        in_10_min: 'Light rain visible near Berlin.',
        next_2_hours: 'Moderate rain appears later in the radar timeline near Berlin.',
        peak_intensity: 'moderate',
        preview_frame_id: 'frame-4',
      },
      timeline,
      rendering: {
        mode: 'external_radar_blob',
        preview_frame_id: 'frame-4',
        frame_count: timeline.length,
        radius_km: 5,
      },
    },
    embedData: {},
  },
  onClose: () => console.log('[Preview] Close weather rain radar fullscreen'),
};
