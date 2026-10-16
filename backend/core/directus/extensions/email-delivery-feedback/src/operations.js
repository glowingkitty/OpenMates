import { createHash } from 'node:crypto';

const COLLECTION = 'email_delivery_suppressions';
const HASH = /^[a-f0-9]{64}$/;
const FIELDS = ['id', 'recipient_hash', 'environment', 'status', 'reason_code', 'last_event_at',
  'last_event_hash', 'suppressed_until', 'recent_failures', 'version'];
const ENVIRONMENTS = new Set(['development', 'production', 'staging', 'self-host', 'ci', 'other']);
const REASONS = new Set(['recipient_disabled', 'recipient_invalid', 'delivered', 'mailbox_full', 'temporary_failure', 'unknown_failure']);

export class FeedbackError extends Error {
  constructor(code, status = 400) { super(code); this.code = code; this.status = status; }
}

export function suppressionId(environment, recipientHash) {
  const namespace = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex');
  const bytes = createHash('sha1').update(namespace).update(`email-feedback:${environment}:${recipientHash}`).digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function timestamp(value) {
  return typeof value === 'string' && value.length <= 32
    && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    && Number.isFinite(Date.parse(value));
}

export function validateRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)
    || Object.keys(body).some((key) => !['id', 'expected_version', 'data'].includes(key))) throw new FeedbackError('invalid_request');
  const row = body.data;
  if (!row || typeof row !== 'object' || Array.isArray(row)
    || Object.keys(row).length !== FIELDS.length || Object.keys(row).some((key) => !FIELDS.includes(key))) throw new FeedbackError('invalid_fields');
  if (!Number.isSafeInteger(body.expected_version) || body.expected_version < 1
    || row.version !== body.expected_version + 1) throw new FeedbackError('invalid_version');
  if (!ENVIRONMENTS.has(row.environment) || typeof row.recipient_hash !== 'string' || !HASH.test(row.recipient_hash)
    || row.id !== body.id || row.id !== suppressionId(row.environment, row.recipient_hash)) throw new FeedbackError('invalid_identity');
  if (!['clear', 'temporary', 'permanent'].includes(row.status) || !REASONS.has(row.reason_code)
    || typeof row.last_event_hash !== 'string' || !HASH.test(row.last_event_hash)
    || !timestamp(row.last_event_at)) throw new FeedbackError('invalid_state');
  if (row.status === 'temporary') {
    if (!timestamp(row.suppressed_until) || Date.parse(row.suppressed_until) <= Date.parse(row.last_event_at)
      || Date.parse(row.suppressed_until) - Date.parse(row.last_event_at) > 24 * 3600 * 1000) throw new FeedbackError('invalid_cooldown');
  } else if (row.suppressed_until !== null) throw new FeedbackError('invalid_cooldown');
  if (!Array.isArray(row.recent_failures) || row.recent_failures.length > 3
    || row.recent_failures.some((failure) => !failure || typeof failure !== 'object'
      || Object.keys(failure).length !== 2 || !HASH.test(failure.hash) || !timestamp(failure.at)
      || Date.parse(failure.at) > Date.parse(row.last_event_at))) throw new FeedbackError('invalid_failures');
  return row;
}

export async function updateSuppression(database, body) {
  const row = validateRequest(body);
  // Directus updateMany(keys,data) ignores query filters during the write. Keep
  // this CAS in SQL, including immutable identity and event timestamp guards.
  const query = database(COLLECTION).where({id: row.id, version: body.expected_version,
    environment: row.environment, recipient_hash: row.recipient_hash})
    .where('last_event_at', '<=', row.last_event_at);
  if (row.status !== 'permanent') query.whereNot('status', 'permanent');
  const saved = await query.update({...row, recent_failures: JSON.stringify(row.recent_failures)}).returning(FIELDS);
  if (!Array.isArray(saved) || saved.length !== 1) throw new FeedbackError('version_conflict', 409);
  return saved[0];
}
