export type WorkflowSkillSummaryStrings = {
  in: string;
  to: string;
  separator?: string;
  dateRangeSeparator?: string;
};

const MAX_VALUE_LENGTH = 48;
const MAX_SUMMARY_LENGTH = 104;

const hiddenFieldPattern = /(?:^|_)(?:id|ids|key|keys|secret|secrets|token|tokens|password|passwords|passphrase|credential|credentials|authorization|bearer|cookie|cookies|hash|nonce|private_key|api_key|access_key|refresh_key)(?:$|_)/i;
const operationalFields = new Set([
  'provider',
  'providers',
  'count',
  'max_results',
  'limit',
  'offset',
  'page',
  'sort',
  'sort_by',
  'format',
  'currency',
  'language',
  'locale',
  'timezone',
  'unit',
  'units',
]);

const preferredFields = [
  'query',
  'location',
  'subject',
  'topic',
  'name',
  'title',
  'flight_number',
  'origin',
  'destination',
  'date',
  'departure_date',
  'start_date',
  'end_date',
  'check_in_date',
  'check_out_date',
  'city',
  'address',
];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function isHiddenField(field: string): boolean {
  const normalized = field.replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/[-.]/g, '_');
  return hiddenFieldPattern.test(normalized);
}

function canonicalRequest(input: Record<string, unknown>): Record<string, unknown> {
  const request = Array.isArray(input.requests) ? record(input.requests[0]) : {};
  return Object.keys(request).length ? { ...input, ...request } : input;
}

function truncate(value: string, limit: number): string {
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(1, limit - 1)).trimEnd()}…`;
}

function safeValue(input: Record<string, unknown>, field: string): string {
  if (isHiddenField(field)) return '';
  const value = input[field];
  if (typeof value !== 'string' && typeof value !== 'number') return '';
  if (typeof value === 'number' && !Number.isFinite(value)) return '';
  const text = String(value).replace(/\s+/g, ' ').trim();
  if (!text || ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']')))) return '';
  return truncate(text, MAX_VALUE_LENGTH);
}

function pair(first: string, connector: string, second: string): string {
  if (first && second) return `${first} ${connector.trim()} ${second}`;
  return first || second;
}

function finish(summary: string): string {
  return truncate(summary.trim(), MAX_SUMMARY_LENGTH);
}

function dateRange(input: Record<string, unknown>, startField: string, endField: string, separator: string): string {
  return pair(safeValue(input, startField), separator, safeValue(input, endField));
}

function connectionSummary(input: Record<string, unknown>, strings: WorkflowSkillSummaryStrings): string {
  const firstLeg = Array.isArray(input.legs) ? record(input.legs[0]) : {};
  const origin = safeValue(input, 'origin') || safeValue(firstLeg, 'origin');
  const destination = safeValue(input, 'destination') || safeValue(firstLeg, 'destination');
  return pair(origin, strings.to, destination);
}

function genericSummary(input: Record<string, unknown>, strings: WorkflowSkillSummaryStrings): string {
  const query = safeValue(input, 'query');
  const location = safeValue(input, 'location');
  if (query && location) return pair(query, strings.in, location);

  const origin = safeValue(input, 'origin');
  const destination = safeValue(input, 'destination');
  if (origin || destination) return pair(origin, strings.to, destination);

  const start = safeValue(input, 'start_date') || safeValue(input, 'check_in_date');
  const end = safeValue(input, 'end_date') || safeValue(input, 'check_out_date');
  const range = pair(start, strings.dateRangeSeparator ?? '–', end);

  const orderedKeys = [
    ...preferredFields,
    ...Object.keys(input).filter((key) => !preferredFields.includes(key)),
  ];
  const values: string[] = [];
  for (const key of orderedKeys) {
    if (isHiddenField(key) || operationalFields.has(key)) continue;
    if (['start_date', 'end_date', 'check_in_date', 'check_out_date'].includes(key) && range) continue;
    const value = safeValue(input, key);
    if (value && !values.includes(value)) values.push(value);
    if (values.length === (range ? 1 : 2)) break;
  }
  if (range) values.push(range);
  return values.slice(0, 2).join(strings.separator ?? ' · ');
}

/**
 * Returns the one or two inputs that best identify an app-skill invocation.
 * Nested request payloads are accepted directly or through `requests[0]`.
 */
export function workflowSkillInputSummary(
  appId: string,
  skillId: string,
  input: Record<string, unknown>,
  strings: WorkflowSkillSummaryStrings,
): string {
  const canonical = canonicalRequest(input);
  const key = `${appId}:${skillId}`;
  const separator = strings.separator ?? ' · ';
  const rangeSeparator = strings.dateRangeSeparator ?? '–';

  if (key === 'events:search') {
    return finish(pair(safeValue(canonical, 'query'), strings.in, safeValue(canonical, 'location')));
  }
  if (key === 'travel:search_connections') {
    return finish(connectionSummary(canonical, strings));
  }
  if (key === 'travel:search_stays') {
    const dates = dateRange(canonical, 'check_in_date', 'check_out_date', rangeSeparator);
    return finish([safeValue(canonical, 'query'), dates].filter(Boolean).join(separator));
  }
  if (key === 'weather:forecast') {
    const dates = dateRange(canonical, 'start_date', 'end_date', rangeSeparator);
    return finish([safeValue(canonical, 'location'), dates].filter(Boolean).join(separator));
  }
  if (key === 'weather:rain_radar') return finish(safeValue(canonical, 'location'));
  if (key === 'news:search' || key === 'home:search') return finish(safeValue(canonical, 'query'));

  return finish(genericSummary(canonical, strings));
}
