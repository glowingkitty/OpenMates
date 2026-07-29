// frontend/packages/ui/src/components/embeds/travel/fareDisplay.ts
//
// Shared display helpers for travel connection fare metadata.
// Backend providers now emit structured fare state for partial fares,
// pass-covered routes, timetable-only routes, and legacy priced results.
// Keeping these rules together prevents the preview and fullscreen renderers
// from drifting when providers expose different fare confidence levels.

export interface TravelFare {
  amount?: number | string | null;
  currency?: string | null;
  is_partial?: boolean | null;
  is_pass_only?: boolean | null;
  covered_by_passes?: string[] | null;
  pricing_provider?: string | null;
  confidence?: string | null;
  summary?: string | null;
}

export interface TravelFareSource {
  fare?: TravelFare | null;
  total_price?: number | string | null;
  price?: number | string | null;
  currency?: string | null;
  fare_is_partial?: boolean | null;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value;
  if (value === 'true') return true;
  if (value === 'false') return false;
  return undefined;
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function stringArrayValue(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === 'string' && value.length > 0) return [value];
  return [];
}

function flatStringArrayValue(content: Record<string, unknown>, fieldName: string, maxItems = 10): string[] {
  const direct = stringArrayValue(content[fieldName]);
  if (direct.length > 0) return direct;

  const values: string[] = [];
  for (let i = 0; i < maxItems; i++) {
    const value = content[`${fieldName}_${i}`];
    if (typeof value === 'string' && value.length > 0) values.push(value);
    else break;
  }
  return values;
}

function fareRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export function normalizeTravelFare(value: unknown): TravelFare | undefined {
  const fare = fareRecord(value);
  if (!fare) return undefined;

  return {
    amount: fare.amount as number | string | null | undefined,
    currency: stringValue(fare.currency) ?? null,
    is_partial: booleanValue(fare.is_partial) ?? null,
    is_pass_only: booleanValue(fare.is_pass_only) ?? null,
    covered_by_passes: stringArrayValue(fare.covered_by_passes),
    pricing_provider: stringValue(fare.pricing_provider) ?? null,
    confidence: stringValue(fare.confidence) ?? null,
    summary: stringValue(fare.summary) ?? null,
  };
}

export function extractTravelFare(content: Record<string, unknown>): TravelFare | undefined {
  const nestedFare = normalizeTravelFare(content.fare);
  if (nestedFare) return nestedFare;

  const hasFlatFare = Object.keys(content).some((key) => key.startsWith('fare_'));
  if (!hasFlatFare) return undefined;

  const coveredByPasses = flatStringArrayValue(content, 'fare_covered_by_passes');

  return {
    amount: content.fare_amount as number | string | null | undefined,
    currency: stringValue(content.fare_currency) ?? null,
    is_partial: booleanValue(content.fare_is_partial) ?? null,
    is_pass_only: booleanValue(content.fare_is_pass_only) ?? null,
    covered_by_passes: coveredByPasses.length > 0
      ? coveredByPasses
      : flatStringArrayValue(content, 'fare_passes_applied'),
    pricing_provider: stringValue(content.fare_pricing_provider) ?? null,
    confidence: stringValue(content.fare_confidence) ?? null,
    summary: stringValue(content.fare_summary) ?? null,
  };
}

function formatPrice(amount: unknown, currency: unknown): string {
  const numericAmount = numberValue(amount);
  const displayAmount = numericAmount === null
    ? String(amount ?? '')
    : numericAmount.toFixed(numericAmount % 1 === 0 ? 0 : 2);
  if (!displayAmount) return '';
  const displayCurrency = stringValue(currency)?.toUpperCase() ?? '';
  return displayCurrency ? `${displayCurrency} ${displayAmount}` : displayAmount;
}

function formatPassName(passId: string): string {
  if (passId === 'deutschland_ticket') return 'Deutschlandticket';
  return passId
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function formatTravelFare(source: TravelFareSource): string {
  const fare = source.fare;
  const confidence = fare?.confidence ?? undefined;

  if (confidence === 'timetable_only') return 'Timetable only';
  if (fare?.is_pass_only === true) {
    const passes = fare.covered_by_passes?.map(formatPassName).filter(Boolean) ?? [];
    return passes.length > 0 ? `Covered by ${passes.join(', ')}` : 'Covered by pass';
  }

  const amount = fare?.amount ?? source.total_price ?? source.price;
  const currency = fare?.currency ?? source.currency;
  const price = formatPrice(amount, currency);
  if (!price) return confidence === 'unknown' ? 'Fare unknown' : '';
  if (fare?.is_partial === true || source.fare_is_partial === true || confidence === 'partial') {
    return `${price} (partial fare)`;
  }
  return price;
}

export function getTravelFareAmount(source: TravelFareSource): number | null {
  const fare = source.fare;
  if (fare?.confidence === 'timetable_only' || fare?.is_pass_only === true) return null;
  return numberValue(fare?.amount ?? source.total_price ?? source.price);
}

export function getTravelFareFallbackLabel(results: TravelFareSource[]): string {
  if (results.some((result) => result.fare?.is_pass_only === true)) return 'Pass covered';
  if (results.some((result) => result.fare?.confidence === 'timetable_only')) return 'Timetable only';
  if (results.some((result) => result.fare?.confidence === 'unknown')) return 'Fare unknown';
  return '';
}

export function formatFareCoverage(value?: string | null): string {
  switch (value) {
    case 'paid':
      return 'Paid fare';
    case 'pass_covered':
      return 'Pass covered';
    case 'timetable_only':
      return 'Timetable only';
    case 'unknown':
      return 'Fare unknown';
    default:
      return '';
  }
}
