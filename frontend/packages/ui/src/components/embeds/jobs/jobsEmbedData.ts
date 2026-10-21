export type EmbedStatus = 'processing' | 'finished' | 'error' | 'cancelled';

export interface JobResult {
  embed_id: string;
  id?: string;
  title?: string;
  company?: string | null;
  url?: string;
  apply_url?: string | null;
  location?: string | null;
  country?: string | null;
  remote?: boolean | null;
  employment_type?: string | null;
  published_at?: string | null;
  description?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_period?: string | null;
  provider?: string;
  sector?: string | null;
  role?: string | null;
  seniority?: string | null;
  organization_type?: string | null;
  work_arrangement?: string | null;
  salary_text?: string | null;
  valid_through?: string | null;
  impact?: string | null;
  detail_status?: string | null;
}

export function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

export function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function safeExternalUrl(value: unknown): string | undefined {
  const raw = stringValue(value);
  if (!raw) return undefined;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function jobProviderLabel(value: unknown): string | undefined {
  const provider = stringValue(value);
  if (!provider) return undefined;
  switch (provider.toLowerCase()) {
    case 'jobtech': return 'JobTech';
    case 'arbeitnow': return 'Arbeitnow';
    case 'arbeitsagentur': return 'Arbeitsagentur';
    case 'eighty_thousand_hours': return '80,000 Hours';
    case 'hard_problems': return 'Hard Problems';
    default: return provider;
  }
}

/** TOON flattens primitive arrays to pipe-delimited strings in stored embeds. */
export function parsePipeList(value: unknown): string[] {
  const entries = Array.isArray(value) ? value : [value];
  return entries.flatMap((entry) => typeof entry === 'string'
    ? entry.split('|').map((part) => part.trim()).filter(Boolean)
    : []);
}

/** Request scope comes from parent metadata; no child listings are needed. */
export function jobSearchScope(content: Record<string, unknown>): string {
  const location = stringValue(content.location);
  const selected = parsePipeList(content.countries).filter((country) => country === 'DE' || country === 'SE');
  const fallback = stringValue(content.country);
  const countries = selected.length ? [...new Set(selected)] : fallback && /^[A-Z]{2}$/.test(fallback) ? [fallback] : [];
  return [location, countries.join(', ')].filter(Boolean).join(' · ');
}

export function normalizeJob(embedId: string, content: Record<string, unknown>): JobResult {
  return {
    embed_id: stringValue(content.embed_id) ?? embedId,
    id: stringValue(content.id),
    title: stringValue(content.title),
    company: stringValue(content.company),
    url: safeExternalUrl(content.url),
    apply_url: safeExternalUrl(content.apply_url),
    location: stringValue(content.location),
    country: stringValue(content.country),
    remote: typeof content.remote === 'boolean' ? content.remote : null,
    employment_type: stringValue(content.employment_type),
    published_at: stringValue(content.published_at),
    description: stringValue(content.description),
    salary_min: numberValue(content.salary_min),
    salary_max: numberValue(content.salary_max),
    salary_currency: stringValue(content.salary_currency),
    salary_period: stringValue(content.salary_period),
    provider: stringValue(content.provider),
    sector: stringValue(content.sector),
    role: stringValue(content.role),
    seniority: stringValue(content.seniority),
    organization_type: stringValue(content.organization_type),
    work_arrangement: stringValue(content.work_arrangement),
    salary_text: stringValue(content.salary_text),
    valid_through: stringValue(content.valid_through),
    impact: stringValue(content.impact),
    detail_status: stringValue(content.detail_status),
  };
}

export function previewJobs(content: Record<string, unknown>): JobResult[] {
  const raw = content.preview_results;
  if (!Array.isArray(raw)) return [];
  return raw.slice(0, 6).flatMap((value, index) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    return [normalizeJob(`preview-${index}`, value as Record<string, unknown>)];
  });
}

export function jobSalary(job: JobResult): string | undefined {
  const min = job.salary_min;
  const max = job.salary_max;
  const currency = stringValue(job.salary_currency);
  if ((min == null && max == null) || !currency) return undefined;
  const format = (value: number) => {
    try { return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(value); }
    catch { return `${currency} ${new Intl.NumberFormat().format(value)}`; }
  };
  const amount = min != null && max != null
    ? min === max ? format(min) : `${format(min)}–${format(max)}`
    : format((min ?? max)!);
  return job.salary_period ? `${amount} / ${job.salary_period}` : amount;
}

export function jobDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}
