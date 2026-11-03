/** Display labels for admitted travel points; coordinates remain in the source content. */
export function travelPointLabel(value: unknown): string | undefined {
  if (typeof value === 'string') return value.trim() ? value : undefined;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const name = (value as Record<string, unknown>).name;
  return typeof name === 'string' && name.trim() ? name : undefined;
}

function firstLabel(...values: unknown[]): string | undefined {
  for (const value of values) {
    const label = travelPointLabel(value);
    if (label) return label;
  }
  return undefined;
}

/** Legacy provider rows may infer endpoints from complete legs; authored partial legs cannot. */
export function travelConnectionEndpoints(content: Record<string, unknown>, allowLegFallback = false) {
  const legs = Array.isArray(content.legs) ? content.legs : [];
  return {
    origin: firstLabel(content.origin, content.origin_name, content.from,
      allowLegFallback ? legs[0]?.origin : undefined),
    destination: firstLabel(content.destination, content.destination_name, content.to,
      allowLegFallback ? legs.at(-1)?.destination : undefined),
  };
}

/** The overall supplied journey is separate from any partial list of known legs. */
export function travelConnectionOverview(content: Record<string, unknown>) {
  const endpoints = travelConnectionEndpoints(content);
  const text = (value: unknown) => typeof value === 'string' && value.trim() ? value : undefined;
  const overview = { ...endpoints, departure: text(content.departure), arrival: text(content.arrival), duration: text(content.duration) };
  return Object.values(overview).some(Boolean) ? overview : undefined;
}

/** UI projection only: a supplied leg without provider segments remains a partial leg. */
export function travelLegPresentation(value: unknown): Record<string, unknown>[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((leg): leg is Record<string, unknown> =>
    !!leg && typeof leg === 'object' && !Array.isArray(leg)).map(leg => ({
    ...leg,
    origin: travelPointLabel(leg.origin),
    destination: travelPointLabel(leg.destination),
    segments: Array.isArray(leg.segments) ? leg.segments : [],
  }));
}
