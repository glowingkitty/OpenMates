import { formatTierMoney, headlineTier, normalizeDomain, quote, textValue, years, type DomainTier } from './hostingDomainData';

function quoteLine(label: string, tier: DomainTier | undefined, currency: string): string | null {
  if (!quote(tier)) return null;
  const amount = formatTierMoney(tier, currency, 'year');
  const minimum = tier ? years(tier) : undefined;
  const term = minimum ? `; minimum ${minimum} ${minimum === 1 ? 'year' : 'years'}` : '';
  return `${label}: ${amount} (${quote(tier)?.basis} tax${term})`;
}

/** Encrypted export/copy text reflects checked evidence and separate quote kinds. */
export function renderHostingDomain(content: Record<string, unknown>): string {
  const domain = normalizeDomain(textValue(content.embed_id), content);
  const lines = [domain.domain_unicode || domain.domain_ascii, `Availability: ${domain.availability}`, `Provider: ${domain.provider}`];
  if (domain.domain_ascii && domain.domain_ascii !== domain.domain_unicode) lines.push(`ASCII: ${domain.domain_ascii}`);
  const registration = quoteLine('Registration', headlineTier(domain.registration_tiers), domain.currency || 'EUR');
  const renewal = quoteLine('Renewal', headlineTier(domain.renewal_tiers), domain.currency || 'EUR');
  if (registration) lines.push(registration);
  if (renewal) lines.push(renewal);
  if (domain.checked_at) lines.push(`Checked: ${domain.checked_at}`);
  return lines.join('\n');
}

export function renderHostingSearch(content: Record<string, unknown>): string {
  const lines = [`**Hosting | Search domains**${textValue(content.query) ? ` — ${textValue(content.query)}` : ''}`];
  if (typeof content.checked_count === 'number') lines.push(`Checked: ${content.checked_count}`);
  if (typeof content.available_count === 'number') lines.push(`Available: ${content.available_count}`);
  if (typeof content.unavailable_count === 'number') lines.push(`Unavailable: ${content.unavailable_count}`);
  if (typeof content.unknown_count === 'number' && content.unknown_count > 0) lines.push(`Could not check: ${content.unknown_count}`);
  if (content.partial === true) lines.push('Partial results');
  if (typeof content.error === 'string' && content.error) lines.push(content.error);
  return lines.join('\n');
}
