/**
 * Text renderers for weather embeds.
 * Used by copy/export/CLI paths to turn decoded embed content into plain text.
 */

import { str } from '../../../data/embedTextRenderers';

function fmtTemp(min: unknown, max: unknown): string {
  const minValue = typeof min === 'number' ? `${Math.round(min)}°C` : null;
  const maxValue = typeof max === 'number' ? `${Math.round(max)}°C` : null;
  if (minValue && maxValue) return `${minValue} / ${maxValue}`;
  return maxValue ?? minValue ?? 'n/a';
}

export function renderWeatherForecast(
  content: Record<string, unknown>,
  children?: Record<string, unknown>[]
): string {
  const location = content.location as Record<string, unknown> | undefined;
  const locationName = str(location?.name) ?? str(content.location_name) ?? 'Weather forecast';
  const provider = str(content.provider) ?? 'Weather';
  const days = children?.length ? children : (Array.isArray(content.results) ? content.results as Record<string, unknown>[] : []);
  const lines = [`**${locationName} forecast**`, `Provider: ${provider}`];
  for (const day of days) {
    lines.push(
      `- ${str(day.date) ?? 'date unknown'}: ${str(day.condition) ?? 'forecast'}, ` +
      `${fmtTemp(day.temperature_min_c, day.temperature_max_c)}, ` +
      `${day.precipitation_total_mm ?? 0} mm, ` +
      `${day.precipitation_probability_max_pct ?? 0}% rain`
    );
  }
  return lines.join('\n');
}

export function renderWeatherDay(content: Record<string, unknown>): string {
  const title = `${str(content.location_name) ?? 'Weather'} ${str(content.date) ?? ''}`.trim();
  const lines = [
    `**${title}**`,
    `Condition: ${str(content.condition) ?? 'forecast'}`,
    `Temperature: ${fmtTemp(content.temperature_min_c, content.temperature_max_c)}`,
    `Rain: ${content.precipitation_total_mm ?? 0} mm, ${content.precipitation_probability_max_pct ?? 0}% max probability, ${content.rain_hours ?? 0}h`,
  ];
  return lines.join('\n');
}

export function renderWeatherRainRadar(content: Record<string, unknown>): string {
  const location = content.location as Record<string, unknown> | undefined;
  const locationName = str(location?.name) ?? str(content.location_name) ?? 'Rain radar';
  const provider = str(content.provider) ?? 'Weather';
  const summary = content.summary as Record<string, unknown> | undefined;
  const timeline = Array.isArray(content.timeline) ? content.timeline as Record<string, unknown>[] : [];
  const lines = [
    `**${locationName} rain radar**`,
    `Provider: ${provider}`,
  ];
  if (summary) {
    lines.push(`In 10 min: ${str(summary.in_10_min) ?? 'n/a'}`);
    lines.push(`Next 2 hours: ${str(summary.next_2_hours) ?? 'n/a'}`);
    lines.push(`Peak intensity: ${str(summary.peak_intensity) ?? 'unknown'}`);
  }
  for (const frame of timeline.slice(0, 8)) {
    lines.push(
      `- ${str(frame.label) ?? str(frame.timestamp) ?? 'frame'}: ` +
      `${str(frame.max_intensity) ?? 'unknown'}, ` +
      `${frame.rain_at_location_mm_5min ?? 0} mm / 5 min at location`
    );
  }
  return lines.join('\n');
}
