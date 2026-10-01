/* Atomic encrypted website snapshots and pending per-Check change occurrences. */
import { randomUUID } from 'node:crypto';
const TABLE = 'workflow_website_state';
const FIELDS = new Set(['protocol_version','action','workflow_id','hashed_user_id','run_id','version_id','source_id','expected_revision','rows','blobs','remove_ids','event_id','blob']);
const ROW_FIELDS = new Set(['id','workflow_id','hashed_user_id','source_id','origin_run_id','generation','created_at','observed_at','kind','consumer_key','revision','source_revision','encrypted_ref']);
const BLOB_FIELDS = new Set(['ref','kind','hashed_user_id','ciphertext','checksum','vault_key_ref','key_version','expires_at','created_at']);
export async function fenceWebsiteDeliveries(trx, scope, eventIds, current) {
  if (!eventIds.length) return;
  const members = await trx('workflow_delivery_history').where(scope).whereIn('change_id',eventIds);
  const deliveryScope = {...scope,hashed_user_id:scope.hashed_user_id.replace(/^user_sha256:/,'')};
  for (const deliveryId of new Set(members.map(m=>m.delivery_id))) {
    const delivery = await trx('workflow_chat_deliveries').where({...deliveryScope,delivery_id:deliveryId}).first();
    if (delivery && !delivery.client_persisted_at && !['acknowledged','cancelled','expired'].includes(delivery.status)) {
      await trx('workflow_chat_deliveries').where({id:delivery.id}).update({status:'cancelled',cancelled_at:current,
        encrypted_payload:'',claim_generation:Number(delivery.claim_generation || 0)+1,claim_token_hash:null,revision:Number(delivery.revision || 0)+1});
      await trx('workflow_delivery_history').where({...scope,delivery_id:deliveryId,status:'reserved'}).del();
    }
  }
}
export async function websiteChanges(database, body, now, fail) {
  if (!body || body.protocol_version !== 1 || Object.keys(body).some(k=>!FIELDS.has(k))) fail(400,'invalid_request');
  if (![body.workflow_id,body.hashed_user_id,body.run_id,body.version_id].every(v=>typeof v === 'string' && v.length > 0 && v.length <= 128)) fail(400,'invalid_owner');
  return database.transaction(async trx=> {
    const scope = {workflow_id:body.workflow_id,hashed_user_id:body.hashed_user_id};
    const workflow = await trx('workflows').where(scope).forUpdate().first();
    if (!workflow || workflow.status === 'deleted') fail(404,'workflow_not_found');
    const run = await trx('workflow_runs').where({...scope,run_id:body.run_id}).first();
    if (!run || ['deleted','cancelled','cancellation_requested','failed','completed'].includes(run.status) || run.trigger_type === 'step_test') fail(409,'run_not_writable');
    if (run.version_id !== body.version_id || workflow.current_version_id !== body.version_id) fail(409,'workflow_version_changed');
    const saveBlob = async blob=> {
      if (!blob || Object.keys(blob).some(k=>!BLOB_FIELDS.has(k)) || blob.hashed_user_id !== body.hashed_user_id || blob.kind !== 'website_state' || typeof blob.ref !== 'string' || !blob.ref.startsWith('vault://workflows/website_state/') || typeof blob.ciphertext !== 'string' || !blob.ciphertext || blob.ciphertext.length > 8_000_000 || typeof blob.checksum !== 'string') fail(400,'invalid_blob');
      if (await trx('workflow_encrypted_blobs').where({ref:blob.ref}).first()) fail(409,'blob_exists');
      await trx('workflow_encrypted_blobs').insert({id:randomUUID(),...blob});
    };
    const removeRows = async rows=> {
      await fenceWebsiteDeliveries(trx,scope,rows.filter(r=>r.kind === 'event').map(r=>r.id),Math.floor(now.getTime()/1000));
      for (const row of rows) {
        await trx(TABLE).where({...scope,id:row.id}).del();
        await trx('workflow_encrypted_blobs').where({hashed_user_id:body.hashed_user_id,ref:row.encrypted_ref}).del();
      }
    };
    if (body.action === 'read') {
      const source = await trx(TABLE).where({...scope,id:body.source_id,kind:'snapshot'}).first();
      const events = await trx(TABLE).where({...scope,source_id:body.source_id,kind:'event'}).orderBy('created_at');
      let memberships = events.length ? await trx('workflow_delivery_history').where(scope).whereIn('change_id',events.map(e=>e.id)) : [];
      for (const member of memberships.filter(m=>m.status === 'reserved')) {
        const deliveryRun = await trx('workflow_runs').where({...scope,run_id:member.run_id}).first();
        if (deliveryRun && deliveryRun.version_id !== body.version_id) {
          await fenceWebsiteDeliveries(trx,scope,[member.change_id],Math.floor(now.getTime()/1000));
        }
      }
      if (events.length) memberships = await trx('workflow_delivery_history').where(scope).whereIn('change_id',events.map(e=>e.id));
      return {source:source || null,events,memberships};
    }
    if (body.action === 'commit') {
      const previous = await trx(TABLE).where({...scope,id:body.source_id,kind:'snapshot'}).first();
      if (Number(previous?.revision || 0) !== body.expected_revision) return {conflict:true};
      if (!Array.isArray(body.rows) || body.rows.length < 1 || body.rows.length > 101 || !Array.isArray(body.blobs) || body.rows.length !== body.blobs.length || !Array.isArray(body.remove_ids) || body.remove_ids.length > 100) fail(400,'invalid_rows');
      const refs = new Set(body.blobs.map(b=>b?.ref));
      if (refs.size !== body.blobs.length) fail(400,'invalid_blobs');
      for (const row of body.rows) {
        if (!row || Object.keys(row).some(k=>!ROW_FIELDS.has(k)) || row.workflow_id !== body.workflow_id || row.hashed_user_id !== body.hashed_user_id || row.source_id !== body.source_id || row.origin_run_id !== body.run_id || !refs.has(row.encrypted_ref) || !/^[a-f0-9]{64}$/.test(row.generation || '') || !['snapshot','event'].includes(row.kind) || !Number.isSafeInteger(row.revision) || row.revision < 1 || typeof row.id !== 'string' || (row.kind === 'event' && !/^[a-f0-9]{64}$/.test(row.consumer_key || ''))) fail(400,'invalid_row');
      }
      const snapshots = body.rows.filter(r=>r.kind === 'snapshot');
      if (snapshots.length !== 1 || snapshots[0].id !== body.source_id || snapshots[0].revision !== body.expected_revision + 1) fail(400,'invalid_snapshot');
      if (!Number.isSafeInteger(snapshots[0].observed_at)) fail(400,'invalid_observation');
      if (previous && snapshots[0].observed_at < Number(previous.observed_at || 0)) fail(409,'website_stale_read');
      const oldEvents = await trx(TABLE).where({...scope,source_id:body.source_id,kind:'event'});
      const deleted = oldEvents.filter(r=>body.remove_ids.includes(r.id));
      if (oldEvents.length - deleted.length + body.rows.length - 1 > 100) fail(409,'pending_limit');
      await removeRows(previous ? [...deleted,previous] : deleted);
      for (const blob of body.blobs) await saveBlob(blob);
      for (const row of body.rows) await trx(TABLE).insert(row);
      return {committed:true};
    }
    if (body.action === 'claim_event') {
      const event = await trx(TABLE).where({...scope,id:body.event_id,kind:'event'}).first();
      if (!event) return {claimed:false};
      const current = Math.floor(now.getTime()/1000);
      const other = event.processing_run_id ? await trx('workflow_runs').where({...scope,run_id:event.processing_run_id}).first() : null;
      if (event.processing_run_id !== body.run_id && Number(event.processing_expires_at || 0) > current && ['running','queued'].includes(other?.status)) return {claimed:false};
      await trx(TABLE).where({...scope,id:event.id}).update({processing_run_id:body.run_id,processing_expires_at:current+300});
      return {claimed:true};
    }
    if (body.action === 'update_event') {
      const event = await trx(TABLE).where({...scope,id:body.event_id,kind:'event'}).first();
      if (!event || event.revision !== body.expected_revision) return {conflict:true};
      if (event.processing_run_id && (event.processing_run_id !== body.run_id || Number(event.processing_expires_at || 0) <= Math.floor(now.getTime()/1000))) return {conflict:true};
      if (body.blob) {
        await saveBlob(body.blob);
        await trx(TABLE).where({...scope,id:event.id}).update({encrypted_ref:body.blob.ref,revision:event.revision+1});
        await trx('workflow_encrypted_blobs').where({hashed_user_id:body.hashed_user_id,ref:event.encrypted_ref}).del();
      } else await removeRows([event]);
      return {updated:true};
    }
    fail(400,'unsupported_website_action');
  });
}
