/* Read-only logical object metering. No object body, key, or per-object ledger leaves SQL. */
export const SOURCE_VERSION = 'logical-s3-v1';
export const POLICY_VERSION = 'personal-storage-1gb-3credits-week-v1';
export const LEGACY_SOURCE_VERSION = 'legacy-upload-files-v1';
export const LEGACY_POLICY_VERSION = 'legacy-upload-storage-1gb-3credits-week-v1';
const MAX_OWNERS = 100;
const HASH_RE = /^[0-9a-f]{64}$/;
const USER_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

export class MeteringError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

function boundedOwners(values, kind) {
  if (!Array.isArray(values) || values.length > MAX_OWNERS) {
    throw new MeteringError(400, 'invalid_owner_page');
  }
  const valid = kind === 'team' ? (value) => HASH_RE.test(value) : (value) => USER_ID_RE.test(value);
  if (values.some((value) => typeof value !== 'string' || !valid(value))
      || new Set(values).size !== values.length) {
    throw new MeteringError(400, 'invalid_owner_page');
  }
  return values;
}

function requestedOwners(userIds, teamHashes) {
  const personal = userIds.length
    ? `SELECT 'personal'::text AS owner_kind, u.id::text AS owner_id,
              encode(digest(u.id::text, 'sha256'), 'hex') AS owner_hash
       FROM directus_users u WHERE u.id::text IN (${userIds.map(() => '?').join(',')})`
    : "SELECT 'personal'::text AS owner_kind, NULL::text AS owner_id, NULL::text AS owner_hash WHERE false";
  const team = teamHashes.length
    ? `SELECT 'team'::text AS owner_kind, requested_team.owner_hash AS owner_id,
              requested_team.owner_hash
       FROM (VALUES ${teamHashes.map(() => '(?)').join(',')}) AS requested_team(owner_hash)`
    : "SELECT 'team'::text AS owner_kind, NULL::text AS owner_id, NULL::text AS owner_hash WHERE false";
  return `${personal} UNION ALL ${team}`;
}

export function quoteSql(userIds, teamHashes) {
  const requested = requestedOwners(userIds, teamHashes);
  return `
WITH requested AS (${requested}),
uploads AS (
  SELECT r.owner_id, r.owner_hash, u.file_size_bytes, u.files_metadata::jsonb AS files_metadata
  FROM requested r JOIN upload_files u ON r.owner_kind = 'personal' AND u.user_id = r.owner_id
),
upload_keys AS (
  SELECT 'chatfiles'::text AS bucket, variant.value->>'s3_key' AS object_key,
         min(up.owner_id) AS owner_id, count(DISTINCT up.owner_id) AS owner_count
  FROM uploads up
  CROSS JOIN LATERAL jsonb_each(
    CASE WHEN jsonb_typeof(up.files_metadata) = 'object' THEN up.files_metadata ELSE '{}'::jsonb END
  ) AS variant
  WHERE variant.value->>'s3_key' IS NOT NULL
  GROUP BY variant.value->>'s3_key'
),
source_refs AS (
  SELECT 'cold_archives'::text AS bucket, p.object_key, p.size_bytes::bigint AS size_bytes,
         r.owner_kind, r.owner_id, r.owner_hash, 'chat_pages'::text AS category, 1 AS priority,
         (p.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id
          AND p.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id
          AND s.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id
          AND s.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id
          AND s.chat_id = c.id::text
          AND s.chat_hash = encode(digest(c.id::text, 'sha256'), 'hex')) AS owner_metadata_valid
  FROM requested r
  JOIN chats c
    ON (r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash)
    OR (r.owner_kind = 'personal' AND c.hashed_team_id IS NULL AND c.hashed_user_id = r.owner_hash)
  JOIN chat_message_archive_pages p ON p.chat_id = c.id::text
  JOIN chat_message_archive_segments s ON s.id = p.segment_id
  WHERE p.published = true AND p.read_enabled = true
    AND s.state IN ('reader_active', 'pruned')
    AND coalesce(c.storage_state, 'hot') NOT IN ('cold', 'deleting')

  UNION ALL
  SELECT 'cold_archives', large.value->>'object_key',
         CASE WHEN large.value->>'size_bytes' ~ '^[0-9]{1,12}$'
              THEN (large.value->>'size_bytes')::bigint ELSE NULL END,
         r.owner_kind, r.owner_id, r.owner_hash, 'chat_oversized', 2,
         (p.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id
          AND p.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id
          AND s.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id
          AND s.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id
          AND s.chat_id = c.id::text
          AND s.chat_hash = encode(digest(c.id::text, 'sha256'), 'hex'))
  FROM requested r
  JOIN chats c
    ON (r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash)
    OR (r.owner_kind = 'personal' AND c.hashed_team_id IS NULL AND c.hashed_user_id = r.owner_hash)
  JOIN chat_message_archive_pages p ON p.chat_id = c.id::text
  JOIN chat_message_archive_segments s ON s.id = p.segment_id
  CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(p.large_objects::jsonb) = 'array'
         THEN p.large_objects::jsonb ELSE '[]'::jsonb END
  ) AS large
  WHERE p.published = true AND p.read_enabled = true
    AND s.state IN ('reader_active', 'pruned')
    AND coalesce(c.storage_state, 'hot') NOT IN ('cold', 'deleting')

  UNION ALL
  SELECT p.logical_bucket, p.object_key, p.size_bytes::bigint,
         r.owner_kind, r.owner_id, r.owner_hash, 'cold_chat_graphs', 3,
         (m.resource_type = 'chat'
          AND m.hashed_resource_id = encode(digest(c.id::text, 'sha256'), 'hex')
          AND m.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id
          AND m.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id)
  FROM requested r
  JOIN chats c
    ON (r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash)
    OR (r.owner_kind = 'personal' AND c.hashed_team_id IS NULL AND c.hashed_user_id = r.owner_hash)
  JOIN cold_archive_manifests m ON m.resource_id = c.id::text AND m.state = 'cold'
  JOIN cold_archive_parts p ON p.archive_id = m.archive_id AND p.generation = m.active_generation
  WHERE c.storage_state = 'cold'

  UNION ALL
  SELECT 'cold_archives', o.payload_s3_key, o.payload_size_bytes::bigint,
         r.owner_kind, r.owner_id, r.owner_hash, 'sealed_recovery', 4,
         (o.root_hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id
          AND (c.hashed_team_id IS NOT NULL OR o.hashed_user_id = c.hashed_user_id))
  FROM requested r
  JOIN chats c
    ON (r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash)
    OR (r.owner_kind = 'personal' AND c.hashed_team_id IS NULL AND c.hashed_user_id = r.owner_hash)
  JOIN chat_recovery_outputs o ON o.root_chat_id = c.id
  WHERE o.state = 'PENDING' AND o.payload_storage = 's3' AND o.deleted_at IS NULL
    AND coalesce(c.storage_state, 'hot') <> 'deleting'

  UNION ALL
  SELECT 'chatfiles', d.archive_object_key, d.archive_size_bytes::bigint,
         r.owner_kind, r.owner_id, r.owner_hash, 'embed_versions', 5,
         (d.archive_owner_kind = r.owner_kind
          AND d.archive_owner_hash = r.owner_hash
          AND d.archive_hashed_chat_id = e.hashed_chat_id) IS TRUE
  FROM requested r
  JOIN chats c
    ON (r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash)
    OR (r.owner_kind = 'personal' AND c.hashed_team_id IS NULL AND c.hashed_user_id = r.owner_hash)
  JOIN embeds e ON e.hashed_chat_id = encode(digest(c.id::text, 'sha256'), 'hex')
  JOIN embed_diffs d ON d.embed_id = e.embed_id AND d.hashed_user_id = e.hashed_user_id
  WHERE d.archive_state IN ('reader_active', 'pruned')
    AND coalesce(c.storage_state, 'hot') <> 'deleting'
),
objects AS (
  SELECT bucket, object_key, min(owner_kind) AS owner_kind, min(owner_id) AS owner_id,
         min(owner_hash) AS owner_hash, min(size_bytes) AS size_bytes,
         (array_agg(category ORDER BY priority))[1] AS category,
         count(DISTINCT owner_kind || ':' || owner_hash) AS owner_count,
         min(size_bytes) IS DISTINCT FROM max(size_bytes)
           OR bool_or(owner_metadata_valid IS DISTINCT FROM true)
           OR bool_or(object_key IS NULL OR object_key = '' OR size_bytes IS NULL OR size_bytes <= 0)
           AS invalid
  FROM source_refs GROUP BY bucket, object_key
),
joined AS (
  SELECT o.*, uk.owner_id AS upload_owner_id, uk.owner_count AS upload_owner_count
  FROM objects o LEFT JOIN upload_keys uk ON uk.bucket = o.bucket AND uk.object_key = o.object_key
),
amounts AS (
  SELECT owner_kind, owner_id, category, sum(size_bytes) AS bytes
  FROM joined WHERE upload_owner_id IS NULL AND NOT invalid AND owner_count = 1
  GROUP BY owner_kind, owner_id, category
  UNION ALL
  SELECT 'personal', owner_id, 'legacy_uploads', coalesce(sum(file_size_bytes), 0)::bigint
  FROM uploads GROUP BY owner_id
),
errors AS (
  SELECT EXISTS (
    SELECT 1 FROM joined WHERE invalid OR owner_count <> 1
      OR (upload_owner_id IS NOT NULL AND (upload_owner_count <> 1 OR upload_owner_id <> owner_id))
  ) OR EXISTS (
    SELECT 1 FROM uploads WHERE file_size_bytes IS NULL OR file_size_bytes < 0
  ) OR EXISTS (
    SELECT 1 FROM uploads WHERE (files_metadata IS NULL
      OR jsonb_typeof(files_metadata) <> 'object')
      AND EXISTS (SELECT 1 FROM source_refs ref
                  WHERE ref.bucket = 'chatfiles' AND ref.owner_id = uploads.owner_id)
  ) OR EXISTS (
    SELECT 1 FROM uploads up
    CROSS JOIN LATERAL jsonb_each(
      CASE WHEN jsonb_typeof(up.files_metadata) = 'object'
           THEN up.files_metadata ELSE '{}'::jsonb END
    ) AS variant
    WHERE (jsonb_typeof(variant.value) <> 'object'
      OR coalesce(variant.value->>'s3_key', '') = '')
      AND EXISTS (SELECT 1 FROM source_refs ref
                  WHERE ref.bucket = 'chatfiles' AND ref.owner_id = up.owner_id)
  ) AS incomplete
)
SELECT r.owner_kind, r.owner_id, r.owner_hash,
       floor(extract(epoch FROM statement_timestamp()))::bigint AS measurement_at,
       coalesce((
         SELECT jsonb_object_agg(category, bytes)
         FROM (SELECT category, sum(bytes)::text AS bytes
               FROM amounts a WHERE a.owner_kind = r.owner_kind AND a.owner_id = r.owner_id
               GROUP BY category) grouped
       ), '{}'::jsonb) AS categories,
       (SELECT incomplete FROM errors) AS incomplete
FROM requested r ORDER BY r.owner_kind, r.owner_id
`;
}

export function legacyQuoteSql(userIds) {
  return `
WITH requested AS (${requestedOwners(userIds, [])})
SELECT r.owner_kind, r.owner_id, r.owner_hash,
       floor(extract(epoch FROM statement_timestamp()))::bigint AS measurement_at,
       jsonb_build_object('legacy_uploads', coalesce(sum(u.file_size_bytes), 0)::text) AS categories,
       coalesce(bool_or(u.file_size_bytes IS NULL OR u.file_size_bytes < 0)
                FILTER (WHERE u.id IS NOT NULL), false) AS incomplete
FROM requested r
LEFT JOIN upload_files u ON r.owner_kind = 'personal' AND u.user_id = r.owner_id
GROUP BY r.owner_kind, r.owner_id, r.owner_hash
ORDER BY r.owner_id
`;
}

function safeBytes(value) {
  const bytes = Number(value);
  if (!Number.isSafeInteger(bytes) || bytes < 0) throw new MeteringError(409, 'storage_usage_incomplete');
  return bytes;
}

export function parseQuoteRows(rows, expectedOwners, { legacyOnly = false } = {}) {
  if (!Array.isArray(rows) || rows.length !== expectedOwners) {
    throw new MeteringError(409, 'storage_usage_incomplete');
  }
  const result = [];
  for (const row of rows) {
    if (row.incomplete !== false) throw new MeteringError(409, 'storage_usage_incomplete');
    const categories = {};
    for (const [category, value] of Object.entries(row.categories ?? {})) {
      if (!['legacy_uploads', 'chat_pages', 'chat_oversized', 'cold_chat_graphs',
        'sealed_recovery', 'embed_versions'].includes(category)) {
        throw new MeteringError(409, 'storage_usage_incomplete');
      }
      categories[category] = safeBytes(value);
    }
    const measurementAt = safeBytes(row.measurement_at);
    if (measurementAt === 0) throw new MeteringError(409, 'storage_usage_incomplete');
    const legacyUploadBytes = categories.legacy_uploads ?? 0;
    const logicalS3Bytes = Object.entries(categories)
      .filter(([category]) => category !== 'legacy_uploads')
      .reduce((sum, [, bytes]) => safeBytes(sum + bytes), 0);
    result.push({
      owner_kind: row.owner_kind, owner_id: row.owner_id,
      policy_version: row.owner_kind === 'team' ? 'team-storage-1gb-3credits-week-v1'
        : legacyOnly ? LEGACY_POLICY_VERSION : POLICY_VERSION,
      source_version: legacyOnly ? LEGACY_SOURCE_VERSION : SOURCE_VERSION,
      complete: true, measurement_at: measurementAt, categories, legacy_upload_bytes: legacyUploadBytes,
      logical_s3_bytes: logicalS3Bytes, total_bytes: safeBytes(legacyUploadBytes + logicalS3Bytes),
    });
  }
  return result;
}

export async function quoteUsage(database, input) {
  const userIds = boundedOwners(input?.user_ids ?? [], 'personal');
  const teamHashes = boundedOwners(input?.team_hashes ?? [], 'team');
  const legacyOnly = input?.legacy_only === true;
  if (legacyOnly && teamHashes.length) throw new MeteringError(400, 'invalid_legacy_owner_scope');
  if (!userIds.length && !teamHashes.length) return [];
  const response = await database.raw(
    legacyOnly ? legacyQuoteSql(userIds) : quoteSql(userIds, teamHashes),
    legacyOnly ? userIds : [...userIds, ...teamHashes],
  );
  return parseQuoteRows(response.rows, userIds.length + teamHashes.length, { legacyOnly });
}

/** Fixed nine-row uploaded-file breakdown for settings; never materializes files. */
export async function uploadBreakdown(database, input) {
  const [userId] = boundedOwners([input?.user_id], 'personal');
  const response = await database.raw(`
    WITH categorized AS (
      SELECT CASE
        WHEN lower(coalesce(content_type, '')) LIKE 'image/%' THEN 'images'
        WHEN lower(coalesce(content_type, '')) LIKE 'video/%' THEN 'videos'
        WHEN lower(coalesce(content_type, '')) LIKE 'audio/%' THEN 'audio'
        WHEN lower(coalesce(content_type, '')) = 'application/pdf' THEN 'pdf'
        WHEN lower(coalesce(content_type, '')) LIKE 'text/%'
          OR lower(coalesce(content_type, '')) IN (
            'application/json', 'application/xml', 'application/javascript',
            'application/x-javascript', 'application/typescript', 'application/x-typescript',
            'application/x-sh', 'application/x-python', 'application/x-ruby', 'application/x-perl'
          ) THEN 'code'
        WHEN lower(coalesce(content_type, '')) IN (
          'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
          'application/vnd.oasis.opendocument.text', 'application/rtf'
        ) THEN 'docs'
        WHEN lower(coalesce(content_type, '')) IN (
          'application/vnd.ms-excel',
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
          'application/vnd.oasis.opendocument.spreadsheet'
        ) THEN 'sheets'
        WHEN lower(coalesce(content_type, '')) IN (
          'application/zip', 'application/x-zip-compressed', 'application/x-tar',
          'application/gzip', 'application/x-gzip', 'application/x-bzip2',
          'application/x-7z-compressed', 'application/x-rar-compressed', 'application/vnd.rar'
        ) THEN 'archives'
        ELSE 'other' END AS category, file_size_bytes
      FROM upload_files WHERE user_id = ?
    )
    SELECT category, count(*)::text AS file_count,
           coalesce(sum(file_size_bytes), 0)::text AS bytes_used,
           coalesce(bool_or(file_size_bytes IS NULL OR file_size_bytes < 0), false) AS incomplete
    FROM categorized GROUP BY category
  `, [userId]);
  if (!Array.isArray(response.rows) || response.rows.length > 9) {
    throw new MeteringError(409, 'storage_usage_incomplete');
  }
  const seen = new Set();
  return response.rows.map((row) => {
    if (!['images', 'videos', 'audio', 'pdf', 'code', 'docs', 'sheets', 'archives', 'other']
      .includes(row.category) || seen.has(row.category) || row.incomplete !== false) {
      throw new MeteringError(409, 'storage_usage_incomplete');
    }
    seen.add(row.category);
    const fileCount = safeBytes(row.file_count);
    if (!fileCount) throw new MeteringError(409, 'storage_usage_incomplete');
    return { category: row.category, file_count: fileCount, bytes_used: safeBytes(row.bytes_used) };
  });
}

export async function listPersonalOwnerIds(database, input) {
  const limit = input?.limit ?? MAX_OWNERS;
  const after = input?.after_user_id ?? '';
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_OWNERS
      || (after !== '' && (typeof after !== 'string' || !USER_ID_RE.test(after)))) {
    throw new MeteringError(400, 'invalid_owner_page');
  }
  const response = await database.raw(`
    SELECT u.id::text AS user_id FROM directus_users u
    WHERE u.id::text > ?
      AND NOT EXISTS (
        SELECT 1 FROM storage_billing_owner_state closed
        WHERE closed.user_id = u.id AND closed.closed_at IS NOT NULL
      )
      AND (
        EXISTS (SELECT 1 FROM upload_files f WHERE f.user_id = u.id::text)
        OR EXISTS (SELECT 1 FROM chats c
                   JOIN chat_message_archive_pages p ON p.chat_id = c.id::text
                   WHERE c.hashed_user_id = encode(digest(u.id::text, 'sha256'), 'hex')
                     AND c.hashed_team_id IS NULL AND p.read_enabled = true)
        OR EXISTS (SELECT 1 FROM chats c
                   JOIN cold_archive_manifests m ON m.resource_id = c.id::text
                   WHERE c.hashed_user_id = encode(digest(u.id::text, 'sha256'), 'hex')
                     AND c.hashed_team_id IS NULL AND m.state = 'cold')
        OR EXISTS (SELECT 1 FROM chats c
                   JOIN chat_recovery_outputs o ON o.root_chat_id = c.id
                   WHERE c.hashed_user_id = encode(digest(u.id::text, 'sha256'), 'hex')
                     AND c.hashed_team_id IS NULL AND o.state = 'PENDING'
                     AND o.payload_storage = 's3' AND o.deleted_at IS NULL)
        OR EXISTS (SELECT 1 FROM chats c
                   JOIN embeds e ON e.hashed_chat_id = encode(digest(c.id::text, 'sha256'), 'hex')
                   JOIN embed_diffs d ON d.embed_id = e.embed_id
                   WHERE c.hashed_user_id = encode(digest(u.id::text, 'sha256'), 'hex')
                     AND c.hashed_team_id IS NULL
                     AND d.archive_state IN ('reader_active', 'pruned'))
      )
    ORDER BY u.id::text LIMIT ?
  `, [after, limit]);
  return response.rows.map((row) => row.user_id);
}

/** Small reference model used by tests and reconciliation samples, never by the weekly scan. */
export function sumLogicalReferences(references, uploadedKeys = []) {
  const uploads = new Map(uploadedKeys.map((row) => [`${row.bucket}\0${row.key}`, row.owner]));
  const objects = new Map();
  for (const row of references) {
    const identity = `${row.bucket}\0${row.key}`;
    if (!row.bucket || !row.key || !Number.isSafeInteger(row.bytes) || row.bytes <= 0 || !row.owner) {
      throw new MeteringError(409, 'storage_usage_incomplete');
    }
    const previous = objects.get(identity);
    if (previous && (previous.bytes !== row.bytes || previous.owner !== row.owner)) {
      throw new MeteringError(409, 'storage_usage_incomplete');
    }
    objects.set(identity, row);
  }
  const byOwner = new Map();
  for (const [identity, row] of objects) {
    const uploadOwner = uploads.get(identity);
    if (uploadOwner && uploadOwner !== row.owner) throw new MeteringError(409, 'storage_usage_incomplete');
    if (uploadOwner) continue;
    byOwner.set(row.owner, (byOwner.get(row.owner) ?? 0) + row.bytes);
  }
  return byOwner;
}
