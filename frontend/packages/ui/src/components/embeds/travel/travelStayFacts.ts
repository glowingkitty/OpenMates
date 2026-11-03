function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === 'string' && !!value.trim());
}

function number(value: unknown): number | undefined {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/** Rates can carry their own currency; absent facts never acquire defaults. */
export function travelStayRate(value: unknown, currency?: unknown) {
  const rate = record(value);
  const amount = number(rate.amount ?? value);
  return { amount: amount !== undefined && amount >= 0 ? amount : undefined, currency: text(rate.currency, currency) };
}

export function travelStayCoordinates(content: Record<string, unknown>) {
  for (const value of [content.coordinates, content.gps_coordinates, content]) {
    const point = record(value);
    const latitude = number(point.latitude ?? point.lat ?? point.gps_coordinates_latitude);
    const longitude = number(point.longitude ?? point.lon ?? point.lng ?? point.gps_coordinates_longitude);
    if (latitude !== undefined && longitude !== undefined && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
      return { latitude, longitude };
    }
  }
  return undefined;
}

/** UI-only aliases for the admitted stay fields; no timezone or check-in time is inferred. */
export function travelStayFacts(content: Record<string, unknown>) {
  return {
    nightlyRate: travelStayRate(content.extracted_rate_per_night ?? content.ratePerNight ?? content.rate_per_night ?? content.price ?? content.min_price, content.currency),
    totalRate: travelStayRate(content.extracted_total_rate ?? content.totalRate ?? content.total_rate ?? content.total_price, content.currency),
    checkIn: text(content.check_in),
    checkOut: text(content.check_out),
    coordinates: travelStayCoordinates(content),
    sourceUrl: text(content.booking_url, content.url, content.link),
  };
}
