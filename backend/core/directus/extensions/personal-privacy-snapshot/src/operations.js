import { createHash } from 'node:crypto';
export const MEMORY_FIELDS = ['id','app_id','item_type','item_key','encrypted_item_json','item_version','created_at','updated_at'];
const clock = () => performance.now();
export async function readPersonalPrivacySnapshot(database, body) {
  if (!body || typeof body.user_id !== 'string' || !body.user_id || body.user_id.length > 255
      || body.known_generation != null && (typeof body.known_generation !== 'string' || body.known_generation.length > 100)) {
    throw new Error('invalid_snapshot_request');
  }
  const owner = createHash('sha256').update(body.user_id).digest('hex');
  return database.transaction(async trx => {
    // No cache or replica. Check enforcement before acknowledging equality.
    const started = clock();
    const installed = await trx.raw(`SELECT count(*)::int AS count FROM pg_trigger
      WHERE NOT tgisinternal AND tgenabled IN ('O','A') AND (
        (tgrelid = 'public.user_app_settings_and_memories'::regclass AND
          tgname IN ('personal_privacy_memory_generation','personal_privacy_memory_truncate')) OR
        (tgrelid = 'public.directus_users'::regclass AND tgname = 'personal_privacy_settings_generation') OR
        (tgrelid = to_regclass('public.personal_privacy_generations') AND tgname = 'personal_privacy_clock_reset'))`);
    if (installed.rows[0]?.count !== 4) return {supported:false};
    // Lock the exact owner clock. Mutation AFTER triggers acquire this same row
    // before commit; settings and memory reads thus describe this one generation.
    await trx('personal_privacy_generations').insert({owner_hash:owner}).onConflict('owner_hash').ignore();
    const generation = await trx('personal_privacy_generations').where({owner_hash:owner}).forShare().first();
    if (!generation) throw new Error('snapshot_generation_missing');
    const token = `${generation.epoch}:${generation.generation}`;
    const generation_ms = clock() - started;
    if (body.known_generation === token) return {supported:true, privacy_generation:token, unchanged:true, phase_durations_ms:{generation_read:generation_ms,snapshot_read:0}};
    const readStarted = clock();
    const profile = await trx('directus_users').where({id:body.user_id}).select('id','encrypted_settings').first();
    if (!profile || !Object.hasOwn(profile,'encrypted_settings')) throw new Error('snapshot_owner_missing');
    const memories = await trx('user_app_settings_and_memories').where({hashed_user_id:owner}).whereNull('hashed_team_id')
      .select(MEMORY_FIELDS).orderBy('updated_at','desc');
    return {supported:true, privacy_generation:token, unchanged:false,
      personal_memories:{encrypted_settings:profile.encrypted_settings,memories},
      phase_durations_ms:{generation_read:generation_ms,snapshot_read:clock()-readStarted}};
  });
}
