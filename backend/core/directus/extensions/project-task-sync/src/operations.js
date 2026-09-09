/**
 * Consistent, internal-only Project Task snapshots and incremental replay.
 * The API authorizes the Project before supplying hashed workspace identity.
 * A transaction holds the same workspace clock used by mutation triggers.
 * Only existing encrypted Task fields, key wrappers and safe metadata leave DB.
 * See docs/plans/codex-tasks-orchestration/codex-rebuild-architecture.md.
 */
import { createHash } from 'node:crypto';
const hash = value => createHash('sha256').update(value).digest('hex');
const HASH = /^[0-9a-f]{64}$/;
const RETENTION_DAYS = 7;

export function parseCursor(value, epoch) {
  if (typeof value !== 'string') return null;
  const [generation, revision, extra] = value.split(':');
  if (extra !== undefined || generation !== epoch || !/^\d+$/.test(revision ?? '')) return null;
  return BigInt(revision);
}

export async function readProjectChanges(database, input) {
  if (!input || !/^(personal|team):[0-9a-f]{64}$/.test(input.scope ?? '') || !HASH.test(input.project_hash ?? '')) {
    throw new Error('invalid_sync_scope');
  }
  const { scope, project_hash: projectHash } = input;
  const ownerField = scope.startsWith('team:') ? 'hashed_team_id' : 'hashed_user_id';
  const ownerHash = scope.split(':')[1];
  const scoped = query => {
    query.where(ownerField, ownerHash);
    if (ownerField === 'hashed_user_id') query.whereNull('hashed_team_id');
    return query;
  };
  return database.transaction(async trx => {
    await trx('project_task_sync_clocks').insert({ scope, revision: 0 }).onConflict('scope').ignore();
    const clock = await trx('project_task_sync_clocks').where({ scope }).forUpdate().first();
    const current = BigInt(clock.revision);
    let after = parseCursor(input.cursor, clock.epoch);
    await trx('project_task_sync_changes').where({ scope })
      .where('created_at', '<', trx.raw(`now() - interval '${RETENTION_DAYS} days'`)).delete();
    const earliest = await trx('project_task_sync_changes').where({ scope }).min('revision as revision').first();
    const floor = earliest?.revision == null ? current : BigInt(earliest.revision) - 1n;
    if (after !== null && (after > current || after < floor)) after = null;
    const reset = after === null;
    let changedIds;
    if (!reset) {
      const changes = await trx('project_task_sync_changes').where({ scope })
        .where('revision', '>', after.toString())
        .whereRaw('project_hashes @> ?::jsonb', [JSON.stringify([projectHash])])
        .distinct('task_id');
      changedIds = changes.map(row => row.task_id);
    }
    const tasksQuery = scoped(trx('user_tasks')).whereRaw('linked_project_hashes::jsonb @> ?::jsonb', [JSON.stringify([projectHash])]);
    if (!reset) tasksQuery.whereIn('task_id', changedIds);
    const tasks = await tasksQuery.select('*').orderBy('task_id');
    const ids = tasks.map(task => task.task_id);
    const idHashes = ids.map(hash);
    // Project wrappers deliberately have no team scope; task membership above
    // already authorizes the IDs. Return only this Project's wrapper, not keys
    // belonging to a different chat, plan, user or Project.
    const wrappers = ids.length ? await trx('user_task_key_wrappers')
      .whereIn('hashed_task_id', idHashes).where({ key_type: 'project', hashed_project_id: projectHash })
      .where(builder => builder.whereNull('expires_at').orWhere('expires_at', '>', Math.floor(Date.now() / 1000)))
      .select('*') : [];
    const activity = ids.length ? await scoped(trx('user_task_activity')).whereIn('task_id', ids)
      .whereNull('deleted_at').distinctOn('task_id').orderBy('task_id')
      .orderBy('created_at', 'desc').orderBy('entry_id', 'desc').select('*') : [];
    const dependencies = ids.length ? await scoped(trx('user_work_dependencies'))
      .where({ source_kind: 'task' }).whereIn('source_id', ids).select('*') : [];
    const targetIds = dependencies.filter(edge => edge.target_kind === 'task').map(edge => edge.target_id);
    const targetTasks = targetIds.length ? await scoped(trx('user_tasks')).whereIn('task_id', targetIds)
      .select('task_id', 'status') : [];
    const statuses = new Map(targetTasks.map(task => [task.task_id, task.status]));
    const wrapperMap = new Map();
    for (const wrapper of wrappers) {
      const entries = wrapperMap.get(wrapper.hashed_task_id) ?? [];
      entries.push(wrapper);
      wrapperMap.set(wrapper.hashed_task_id, entries);
    }
    const activityMap = new Map(activity.map(entry => [entry.task_id, entry]));
    const dependencyMap = new Map();
    for (const edge of dependencies) {
      const entries = dependencyMap.get(edge.source_id) ?? [];
      entries.push({ ...edge, target_status: statuses.get(edge.target_id) ?? null });
      dependencyMap.set(edge.source_id, entries);
    }
    const present = new Set(ids);
    return {
      reset,
      cursor: `${clock.epoch}:${current}`,
      tasks: tasks.map(task => ({
        ...task,
        key_wrappers: wrapperMap.get(hash(task.task_id)) ?? [],
        latest_activity: activityMap.get(task.task_id) ?? null,
        dependencies: dependencyMap.get(task.task_id) ?? [],
      })),
      removed_task_ids: reset ? [] : changedIds.filter(id => !present.has(id)),
    };
  });
}

/** First-party deletion receipts contain only an owner-bound blind chat index. */
export async function unlinkDeletedExternalChat(database, input) {
  if (!/^(personal|team):[0-9a-f]{64}$/.test(input?.scope ?? '') || input.provider !== 'codex' || !HASH.test(input.lookup_hash ?? '') || !HASH.test(input.event_id ?? '')) throw new Error('invalid_sync_scope');
  const ownerField = input.scope.startsWith('team:') ? 'hashed_team_id' : 'hashed_user_id';
  return database.transaction(async trx => {
    // Lock existing rows before the chat fence, matching normal UPDATE order.
    // A claim on a previously unlinked row either commits before our subsequent
    // UPDATE or sees the durable tombstone after acquiring the same fence.
    const existing = trx('user_tasks').where(ownerField, input.scope.split(':')[1])
      .where({external_chat_provider: input.provider, external_chat_lookup_hash: input.lookup_hash});
    if (ownerField === 'hashed_user_id') existing.whereNull('hashed_team_id');
    await existing.orderBy('task_id').forUpdate().select('task_id');
    await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`${input.scope}:${input.provider}:${input.lookup_hash}`]);
    await trx('task_external_chat_deletions').insert({scope: input.scope, provider: input.provider, lookup_hash: input.lookup_hash, event_id: input.event_id})
      .onConflict(['scope', 'provider', 'lookup_hash']).ignore();
    const query = trx('user_tasks').where(ownerField, input.scope.split(':')[1]).where({external_chat_provider: input.provider, external_chat_lookup_hash: input.lookup_hash});
    if (ownerField === 'hashed_user_id') query.whereNull('hashed_team_id');
    const changed = await query.update({external_chat_provider: null, external_chat_lookup_hash: null, encrypted_external_chat_id: null,
      encrypted_external_chat_title: null, queue_state: 'none', ai_execution_state: null,
      status: trx.raw("CASE WHEN status = 'in_progress' THEN 'todo' ELSE status END"),
      version: trx.raw('version + 1'), updated_at: Math.floor(Date.now() / 1000)}).returning('task_id');
    return {unlinked_tasks: changed.length, event_id: input.event_id};
  });
}
