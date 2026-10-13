/** Preserve the three meanings of an optional Jobs remote filter. */
export type JobCountry = 'DE' | 'SE';

const JOB_COUNTRIES: JobCountry[] = ['DE', 'SE'];

function validCountries(value: unknown): JobCountry[] {
  return JOB_COUNTRIES.filter(country => Array.isArray(value) && value.includes(country));
}

export function jobCountryOverrides(input: Record<string, unknown>): Array<{ index: number; countries: JobCountry[] }> {
  return Array.isArray(input.requests) ? input.requests.flatMap((request, index) => {
    const record = request && typeof request === 'object' ? request as Record<string, unknown> : {};
    const countries = JOB_COUNTRIES.filter(country => validCountries(record.countries).includes(country) || record.country === country);
    return countries.length ? [{ index, countries }] : [];
  }) : [];
}

/** Show an existing shared selection, then legacy request choices, then the schema default. */
export function jobCountriesSelection(input: Record<string, unknown>): JobCountry[] {
  const shared = validCountries(input.countries);
  if (shared.length) return shared;
  const legacy = jobCountryOverrides(input).flatMap(override => override.countries);
  const selected = JOB_COUNTRIES.filter(country => legacy.includes(country));
  return selected.length ? selected : ['DE'];
}

/** Keep at least one country; a shared edit replaces hidden per-request overrides. */
export function toggleJobCountry(input: Record<string, unknown>, country: JobCountry): Record<string, unknown> {
  const selected = jobCountriesSelection(input);
  const countries = selected.includes(country) ? selected.filter(item => item !== country) : JOB_COUNTRIES.filter(item => selected.includes(item) || item === country);
  if (!countries.length) return input;
  const requests = Array.isArray(input.requests) ? input.requests.map(request => {
    if (!request || typeof request !== 'object') return request;
    const rest = { ...(request as Record<string, unknown>) };
    delete rest.country;
    delete rest.countries;
    return rest;
  }) : input.requests;
  return { ...input, countries, ...(requests === undefined ? {} : { requests }) };
}

export function jobRemoteSelection(value: unknown): '' | 'true' | 'false' {
  return value === true ? 'true' : value === false ? 'false' : '';
}

export function jobRemoteValue(selection: string): boolean | undefined {
  return selection === 'true' ? true : selection === 'false' ? false : undefined;
}

export function updateJobRequestField(current: Record<string, unknown>, name: string, next: unknown): Record<string, unknown> {
  const updated = { ...current };
  if (name === 'remote' && next === undefined) delete updated.remote;
  else updated[name] = next;
  return updated;
}

export function addJobRequest<T>(requests: T[], create: () => T, maxItems = 5): T[] {
  return requests.length < maxItems ? [...requests, create()] : requests;
}

export function removeJobRequest<T>(requests: T[], index: number, minItems = 1): T[] {
  return requests.length > minItems && index >= 0 && index < requests.length
    ? requests.filter((_, itemIndex) => itemIndex !== index)
    : requests;
}
