/** Model output adaptation only: no input or detections are stored outside memory. */
import { detectPII, PII_TYPE_TO_CATEGORY, type PIIDetectionOptions, type PIIMatch, type PIIType } from './piiDetectionService';

export interface WebPIIEntity { label: string; original: string; start: number; end: number; confidence: number }

// URLs stay intact for embed extraction. Organisations are not natural persons.
// All address parts share the existing ADDRESS restoration/mapping format.
const LABEL_TYPES: Record<string, PIIType> = {
  GIVEN_NAME: 'PERSON_NAME', SURNAME: 'PERSON_NAME',
  STREET_NAME: 'ADDRESS', BUILDING_NUMBER: 'ADDRESS', SECONDARY_ADDRESS: 'ADDRESS',
  CITY: 'ADDRESS', STATE: 'ADDRESS', ZIP_CODE: 'ADDRESS', EMAIL: 'EMAIL', PHONE: 'PHONE',
  CREDIT_CARD: 'CREDIT_CARD', BANK_ACCOUNT: 'BANK_ACCOUNT', ROUTING_NUMBER: 'BANK_ACCOUNT',
  GOVERNMENT_ID: 'GOVERNMENT_ID', PASSPORT: 'PASSPORT', DRIVERS_LICENSE: 'DRIVERS_LICENSE',
  TAX_ID: 'TAX_ID', SSN: 'SSN', IMEI: 'IMEI',
};
export const WEB_PII_LABELS = [...Object.keys(LABEL_TYPES), 'IP_ADDRESS'];

/** Stable across composer markup/canonical text offset changes; never persisted. */
export function modelPIIMatchId(type: PIIType, value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i++) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619);
  return `pii-model-${type}-${(hash >>> 0).toString(36)}`;
}

function protectedRanges(text: string): Array<{ start: number; end: number }> {
  return Array.from(text.matchAll(/https?:\/\/[^\s]+|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi), m => ({ start: m.index!, end: m.index! + m[0].length }));
}
const overlaps = (start: number, end: number, range: { start: number; end: number }) => start < range.end && end > range.start;
const mandatoryCategories = new Set(['api_keys', 'generic_secrets', 'private_keys', 'jwt_tokens']);

function isWholeIBAN(value: string): boolean {
  // Reuse the existing ISO 7064 check rather than accepting a broader neural
  // span solely by label. PHONE can otherwise claim the account's digit runs
  // before the synchronous detector gets to its validated IBAN pattern.
  return detectPII(value, { disabledCategories: new Set(['phone_numbers']) }).some(match =>
    match.type === 'IBAN' && match.startIndex === 0 && match.endIndex === value.length);
}
const generatedPlaceholderTypes = [...new Set([...Object.keys(PII_TYPE_TO_CATEGORY),
  'AWS_KEY', 'AWS_SECRET', 'GITHUB_TOKEN', 'GOOGLE_KEY', 'HF_TOKEN', 'SECRET', 'JWT_TOKEN', 'CARD', 'IP', 'HOME_PATH', 'USER_HOST', 'MAC', 'PLATE', 'WALLET',
])];
const generatedPlaceholderPattern = new RegExp(`\\[(?:${generatedPlaceholderTypes.join('|')})_[1-9][0-9]*(?:_[A-Za-z0-9_-]+)?\\]`, 'g');

function knownCustomPlaceholderRanges(text: string, options: PIIDetectionOptions): Array<{ start: number; end: number }> {
  const ranges: Array<{ start: number; end: number }> = [];
  for (const entry of options.personalDataEntries ?? []) {
    if (!entry.replaceWith) continue;
    const token = entry.replaceWith.startsWith('[') ? entry.replaceWith : `[${entry.replaceWith}]`;
    let start = text.indexOf(token);
    while (start !== -1) {
      ranges.push({ start, end: start + token.length });
      start = text.indexOf(token, start + token.length);
    }
  }
  return ranges;
}

export function mergeWebPIIMatches(text: string, entities: WebPIIEntity[], options: PIIDetectionOptions = {}): PIIMatch[] {
  // Reserve excluded spans too: restoring an API key must not expose it to a
  // second detector which would immediately mask an overlapping substring.
  const unexcluded = { ...options, excludedIds: undefined };
  const basic = detectPII(text, options);
  const excludedRanges = detectPII(text, unexcluded)
    .filter(match => options.excludedIds?.has(match.id))
    .map(match => ({ start: match.startIndex, end: match.endIndex }));
  const reserved = [...excludedRanges];
  const knownPlaceholders = knownCustomPlaceholderRanges(text, options);
  const result: PIIMatch[] = [];
  const counts: Record<string, number> = {};
  let placeholderNonce: string | undefined;
  for (const match of basic) {
    // Exact configured replacement tokens are known output. Bracket syntax by
    // itself never shields mandatory secret/configured-value detection.
    if (match.id.startsWith('pii-PERSONAL_DATA-') && knownPlaceholders.some(r => overlaps(match.startIndex, match.endIndex, r))) continue;
    if (reserved.some(r => overlaps(match.startIndex, match.endIndex, r))) continue;
    reserved.push({ start: match.startIndex, end: match.endIndex });
    if (!options.excludedIds?.has(match.id)) result.push(match);
  }
  // Exclusions and mandatory mappings are hard boundaries. A validated whole
  // IBAN may replace contained PHONE false positives; other basic matches keep
  // their IDs, types and placeholders.
  const hardReserved = [
    ...excludedRanges,
    ...result.filter(match => match.id.startsWith('pii-PERSONAL_DATA-') || mandatoryCategories.has(PII_TYPE_TO_CATEGORY[match.type])).map(match => ({ start: match.startIndex, end: match.endIndex })),
    ...knownPlaceholders,
    ...Array.from(text.matchAll(generatedPlaceholderPattern), m => ({ start: m.index!, end: m.index! + m[0].length })),
    ...protectedRanges(text),
  ];
  for (const entity of [...entities].sort((a, b) => a.start - b.start || b.end - a.end)) {
    let type = LABEL_TYPES[entity.label];
    if (entity.label === 'IP_ADDRESS') type = entity.original.includes(':') ? 'IPV6' : 'IPV4';
    if (!type) continue;
    // The SDK codec specifies UTF-16 offsets, exactly matching JS/Svelte. Never
    // guess or search/shift offsets when an SDK contract is violated.
    if (!Number.isInteger(entity.start) || !Number.isInteger(entity.end) || entity.start < 0 || entity.end <= entity.start || entity.end > text.length || text.slice(entity.start, entity.end) !== entity.original) {
      throw new Error('PII detector returned invalid character offsets');
    }
    if (options.disabledCategories?.has(PII_TYPE_TO_CATEGORY[type])) continue;
    if (hardReserved.some(r => overlaps(entity.start, entity.end, r))) continue;
    // Reject semantic versions misidentified as IP addresses (e.g. 3.14.159).
    if (type === 'IPV4' && (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(entity.original) || entity.original.split('.').some(part => Number(part) > 255))) continue;
    const id = modelPIIMatchId(type, entity.original);
    if (reserved.some(range => overlaps(entity.start, entity.end, range))) {
      const contained = result.filter(match => overlaps(entity.start, entity.end, { start: match.startIndex, end: match.endIndex }));
      const upgradesPhoneToIBAN = type === 'BANK_ACCOUNT' && contained.length > 0 &&
        contained.every(match => match.type === 'PHONE' && !match.id.startsWith('pii-PERSONAL_DATA-') && match.startIndex >= entity.start && match.endIndex <= entity.end) &&
        isWholeIBAN(entity.original);
      if (!upgradesPhoneToIBAN) continue;
      for (const match of contained) {
        result.splice(result.indexOf(match), 1);
        const index = reserved.findIndex(range => range.start === match.startIndex && range.end === match.endIndex);
        if (index !== -1) reserved.splice(index, 1);
      }
    }
    reserved.push({ start: entity.start, end: entity.end });
    if (options.excludedIds?.has(id)) {
      hardReserved.push({ start: entity.start, end: entity.end });
      continue;
    }
    placeholderNonce ??= crypto.randomUUID().replaceAll('-', '').slice(0, 16);
    counts[type] = (counts[type] ?? 0) + 1;
    result.push({ type, match: entity.original, startIndex: entity.start, endIndex: entity.end, id, placeholder: `[${type}_${counts[type]}_${placeholderNonce}]` });
  }
  return result.sort((a, b) => a.startIndex - b.startIndex);
}
