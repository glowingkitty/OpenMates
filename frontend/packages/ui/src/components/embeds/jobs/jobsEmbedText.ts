/** Plain-text renderers for Jobs search and its individual listings. */
import { resolveResultCount, str, trunc } from '../../../data/embedTextRenderers';
import { jobProviderLabel, safeExternalUrl } from './jobsEmbedData';

function source(value: unknown): string {
  return jobProviderLabel(value) ?? '';
}

/** jobs-job-result — copy a listing with its source and application URL. */
export function renderJobResult(content: Record<string, unknown>): string {
  const title = str(content.title) ?? 'Job listing';
  const company = str(content.company);
  const location = str(content.location);
  const provider = source(content.provider);
  const url = safeExternalUrl(content.url);
  const applyUrl = safeExternalUrl(content.apply_url);
  const lines = [`**${title}**`];
  if (company) lines.push(company);
  if (location) lines.push(location);
  if (content.remote === true) lines.push('Remote');
  if (provider) lines.push(`Source: ${provider}`);
  if (url) lines.push(url);
  if (applyUrl && applyUrl !== url) lines.push(`Apply: ${applyUrl}`);
  return lines.join('\n');
}

/** app:jobs:search — copy a bounded listing summary without fetching children. */
export function renderJobsSearch(
  content: Record<string, unknown>,
  children?: Record<string, unknown>[],
): string {
  const query = str(content.query);
  const lines = [`**Job Search**${query ? ` — "${trunc(query, 60)}"` : ''}`];
  const count = resolveResultCount(content);
  if (count !== null) lines.push(`${count} job${count === 1 ? '' : 's'}`);
  const preview = Array.isArray(content.preview_results) ? content.preview_results : [];
  const listings = children?.length ? children : preview;
  for (const listing of listings.slice(0, 5)) {
    if (!listing || typeof listing !== 'object' || Array.isArray(listing)) continue;
    lines.push('', renderJobResult(listing as Record<string, unknown>));
  }
  if (listings.length > 5) lines.push(`+ ${listings.length - 5} more`);
  return lines.join('\n');
}
