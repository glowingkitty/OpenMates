/* Atomic run-owned delivery membership. Indexed content is HMAC identity only. */
import { randomUUID, createHash } from 'node:crypto';

const FIELDS = new Set(['protocol_version','action','hashed_user_id','workflow_id','run_id','node_id','delivery_id','destination_hash','candidates','expires_at','encrypted_key_ref','delivery','run']);
function uuid5(name) {
  const namespace = Buffer.from('6ba7b8119dad11d180b400c04fd430c8','hex');
  const bytes = createHash('sha1').update(namespace).update(name,'utf8').digest().subarray(0,16);
  bytes[6] = (bytes[6] & 15) | 80; bytes[8] = (bytes[8] & 63) | 128;
  const hex = bytes.toString('hex');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export async function deliveryHistory(database, body, now, fail) {
  if (!body || body.protocol_version !== 1 || Object.keys(body).some(k => !FIELDS.has(k))) fail(400, 'invalid_request');
  if (typeof body.workflow_id !== 'string' || typeof body.hashed_user_id !== 'string') fail(400, 'invalid_owner');
  const current = Math.floor(now.getTime() / 1000);
  return database.transaction(async trx => {
    const workflow = await trx('workflows').where({workflow_id:body.workflow_id, hashed_user_id:body.hashed_user_id}).forUpdate().first();
    if (!workflow || workflow.status === 'deleted') fail(404, 'workflow_not_found');
    const scope = {workflow_id:body.workflow_id, hashed_user_id:body.hashed_user_id};
    const deliveryScope = {workflow_id:body.workflow_id,hashed_user_id:body.hashed_user_id.replace(/^user_sha256:/,'')};
    if (body.action === 'key') {
      let ref = workflow.encrypted_delivery_key_ref;
      if (!ref && body.encrypted_key_ref) {
        if (typeof body.encrypted_key_ref !== 'string' || !body.encrypted_key_ref.startsWith('vault://workflows/delivery_identity_key/')) fail(400,'invalid_key_ref');
        const blob = await trx('workflow_encrypted_blobs').where({ref:body.encrypted_key_ref, hashed_user_id:body.hashed_user_id}).first();
        if (!blob) fail(400,'invalid_key_ref');
        ref = body.encrypted_key_ref;
        await trx('workflows').where({id:workflow.id}).update({encrypted_delivery_key_ref:ref});
      }
      return {encrypted_key_ref:ref || null};
    }
    if (body.action === 'release') {
      const persisted = await trx('workflow_chat_deliveries').where({...deliveryScope,delivery_id:body.delivery_id}).first();
      if (persisted?.client_persisted_at) return {released:false};
      await trx('workflow_delivery_history').where({...scope,delivery_id:body.delivery_id,status:'reserved'}).del();
      return {released:true};
    }
    if (body.action === 'save_run') {
      const row = body.run;
      if (!row || row.run_id !== body.run_id || row.workflow_id !== body.workflow_id || row.hashed_user_id !== body.hashed_user_id) fail(400,'invalid_run');
      const existing = await trx('workflow_runs').where({...scope,run_id:body.run_id}).first();
      if (existing?.status === 'deleted') fail(409,'run_deleted');
      // Preserve a concurrent cancellation checkpoint, even if the worker has an older snapshot.
      if (existing?.status === 'cancellation_requested' && row.status === 'running') {
        row.status = 'cancellation_requested';
        row.record_json = {...row.record_json,status:'cancellation_requested',cancellation_requested_at:existing.cancellation_requested_at};
      }
      if (existing) { delete row.id; await trx('workflow_runs').where({id:existing.id}).update(row); }
      else await trx('workflow_runs').insert(row);
      if (['failed','cancelled'].includes(row.status)) {
        const pending = await trx('workflow_chat_deliveries').where({...deliveryScope,run_id:body.run_id}).whereIn('status',['delivery_pending','claimed']);
        const persistedIds = new Set(pending.filter(d=>d.client_persisted_at).map(d=>d.delivery_id));
        for (const delivery of pending) if (!delivery.client_persisted_at) await trx('workflow_chat_deliveries').where({id:delivery.id}).update({status:'cancelled',cancelled_at:current,encrypted_payload:'',claim_generation:Number(delivery.claim_generation || 0)+1,claim_token_hash:null,revision:Number(delivery.revision || 0)+1});
        const reservations = await trx('workflow_delivery_history').where({...scope,run_id:body.run_id,status:'reserved'});
        for (const reservation of reservations) if (!persistedIds.has(reservation.delivery_id)) await trx('workflow_delivery_history').where({id:reservation.id}).del();
      }
      return {saved:true};
    }
    const runId = body.run_id || body.delivery?.run_id;
    const run = await trx('workflow_runs').where({...scope,run_id:runId}).first();
    if (!run || run.status === 'deleted') fail(409,'run_deleted');
    if (body.action === 'delete_run') {
      const refs = [run.encrypted_output_summary].filter(Boolean);
      const deliveries = await trx('workflow_chat_deliveries').where({...deliveryScope,run_id:runId});
      for (const d of deliveries) {
        if (d.status !== 'acknowledged') await trx('workflow_chat_deliveries').where({id:d.id}).update({status:'cancelled',cancelled_at:current,claim_generation:Number(d.claim_generation || 0)+1,claim_token_hash:null,encrypted_payload:'',encrypted_chat_metadata:null,encrypted_message:null});
      }
      await trx('workflow_delivery_history').where({...scope,run_id:runId}).del();
      // A scrubbed ID tombstone fences stale workers; it contains no result memory.
      await trx('workflow_runs').where({id:run.id}).update({status:'deleted',record_json:null,encrypted_input:null,encrypted_output_summary:null,error_summary:null,cost_summary:null,content_available:false,content_storage:'deleted'});
      return {run_id:runId,status:'deleted',content_refs:refs};
    }
    if (body.action === 'reserve') {
      if (run.trigger_type === 'step_test' || run.status === 'cancellation_requested' || run.status === 'cancelled' || run.status === 'failed') fail(409,'run_not_deliverable');
      if (typeof body.delivery_id !== 'string' || typeof body.node_id !== 'string' || !/^[a-f0-9]{64}$/.test(body.destination_hash || '')) fail(400,'invalid_delivery');
      if (!Array.isArray(body.candidates) || body.candidates.length > 500 || !Number.isInteger(body.expires_at) || body.expires_at <= current) fail(400,'invalid_candidates');
      // Pending expiry releases reservations. Delivered membership survives payload expiry.
      await trx('workflow_delivery_history').where({...scope,status:'reserved'}).where('expires_at','<=',current).del();
      const own = await trx('workflow_delivery_history').where({...scope,delivery_id:body.delivery_id});
      if (own.length) return {selected_indexes:own.map(r=>r.candidate_index)};
      const fingerprints = body.candidates.map(c => c?.fingerprint).filter(v => typeof v === 'string');
      const knownRows = fingerprints.length ? await trx('workflow_delivery_history')
        .where({...scope,destination_hash:body.destination_hash}).whereIn('fingerprint',fingerprints)
        .whereIn('status',['reserved','delivered']).select('fingerprint') : [];
      const knownFingerprints = new Set(knownRows.map(r=>r.fingerprint));
      const selected = [], seen = new Set();
      for (const c of body.candidates) {
        if (!c || Object.keys(c).some(k=>!['index','fingerprint','only_new'].includes(k)) || !Number.isInteger(c.index) || c.index < 0 || !/^[a-f0-9]{64}$/.test(c.fingerprint || '') || typeof c.only_new !== 'boolean') fail(400,'invalid_candidate');
        if (seen.has(c.fingerprint)) continue;
        seen.add(c.fingerprint);
        if (c.only_new && knownFingerprints.has(c.fingerprint)) continue;
        selected.push(c.index);
        await trx('workflow_delivery_history').insert({id:randomUUID(),...scope,run_id:runId,node_id:body.node_id,delivery_id:body.delivery_id,destination_hash:body.destination_hash,fingerprint:c.fingerprint,candidate_index:c.index,status:'reserved',created_at:current,expires_at:body.expires_at});
      }
      return {selected_indexes:selected};
    }
    if (body.action === 'save_delivery') {
      const d = body.delivery;
      const allowed = new Set(['delivery_id','hashed_user_id','workflow_id','run_id','node_id','chat_id','message_id','encrypted_payload','status','revision','claim_generation','claim_token_hash','claim_issued_at','claim_expires_at','claim_device_id','encrypted_chat_metadata','encrypted_message','client_persisted_at','acknowledged_at','cancelled_at','expired_at','created_at','expires_at']);
      if (!d || Object.keys(d).some(k=>!allowed.has(k)) || d.workflow_id !== body.workflow_id || d.hashed_user_id !== deliveryScope.hashed_user_id || d.run_id !== runId) fail(400,'invalid_delivery');
      const existing = await trx('workflow_chat_deliveries').where({...deliveryScope,delivery_id:d.delivery_id}).first();
      if (d.client_persisted_at && !existing?.client_persisted_at) {
        if (!existing || existing.status !== 'claimed' || Number(existing.claim_expires_at || 0) <= current) fail(409,'delivery_claim_expired');
        let metadata, message;
        try { metadata = JSON.parse(d.encrypted_chat_metadata); message = JSON.parse(d.encrypted_message); }
        catch { fail(400,'invalid_client_ciphertext'); }
        const metadataFields = new Set(['encrypted_title','encrypted_category','encrypted_chat_key','created_at','messages_v','title_v']);
        const messageFields = new Set(['role','encrypted_content','encrypted_category','created_at','embeds']);
        if (!metadata || !message || Object.keys(metadata).some(k=>!metadataFields.has(k)) || Object.keys(message).some(k=>!messageFields.has(k)) || message.role !== 'assistant') fail(400,'invalid_client_ciphertext');
        for (const value of [metadata.encrypted_title, metadata.encrypted_category,metadata.encrypted_chat_key,message.encrypted_content]) {
          if (typeof value !== 'string' || !value || value.length > 4_000_000) fail(400,'invalid_client_ciphertext');
        }
        const embeds = message.embeds || [];
        if (!Array.isArray(embeds) || embeds.length > 500) fail(400,'invalid_client_embeds');
        const members = await trx('workflow_delivery_history').where({...scope,delivery_id:d.delivery_id});
        const expected = new Set(members.map(r=>uuid5(`${d.delivery_id}:embed:${r.fingerprint}`)));
        if (embeds.length !== expected.size) fail(400,'selected_embeds_required');
        const sha = value=>createHash('sha256').update(value,'utf8').digest('hex');
        const hashChat = sha(d.chat_id);
        for (const embed of embeds) {
          const allowedEmbed = new Set(['embed_id','encrypted_content','encrypted_type','encrypted_text_preview','embed_keys']);
          if (!embed || Object.keys(embed).some(k=>!allowedEmbed.has(k)) || !expected.delete(embed.embed_id)) fail(400,'invalid_client_embeds');
          for (const value of [embed.encrypted_content,embed.encrypted_type,embed.encrypted_text_preview]) if (typeof value !== 'string' || !value || value.length > 4_000_000) fail(400,'invalid_client_embeds');
          if (!Array.isArray(embed.embed_keys) || embed.embed_keys.length !== 2 || !['master','chat'].every(type=>embed.embed_keys.some(k=>k.key_type === type))) fail(400,'invalid_embed_keys');
          const hashedEmbed = sha(embed.embed_id);
          const previous = await trx('embeds').where({embed_id:embed.embed_id}).first();
          if (previous && previous.hashed_user_id !== deliveryScope.hashed_user_id) fail(409,'embed_conflict');
          if (!previous) {
            await trx('embeds').insert({id:randomUUID(),embed_id:embed.embed_id,hashed_embed_id:hashedEmbed,hashed_chat_id:hashChat,hashed_message_id:sha(d.message_id),hashed_user_id:deliveryScope.hashed_user_id,encrypted_content:embed.encrypted_content,encrypted_type:embed.encrypted_type,encrypted_text_preview:embed.encrypted_text_preview,status:'finished',encryption_mode:'client',created_at:current,updated_at:current});
            for (const key of embed.embed_keys) {
              if (Object.keys(key).some(k=>!['key_type','encrypted_embed_key'].includes(k)) || typeof key.encrypted_embed_key !== 'string' || !key.encrypted_embed_key) fail(400,'invalid_embed_keys');
              await trx('embed_keys').insert({id:randomUUID(),hashed_embed_id:hashedEmbed,key_type:key.key_type,hashed_chat_id:key.key_type === 'chat' ? hashChat : null,encrypted_embed_key:key.encrypted_embed_key,hashed_user_id:deliveryScope.hashed_user_id,created_at:current});
            }
          }
        }
        const chat = await trx('chats').where({id:d.chat_id}).forUpdate().first();
        if (chat && (chat.hashed_user_id !== deliveryScope.hashed_user_id || chat.hashed_team_id)) fail(403,'chat_not_owned');
        if (chat && chat.encrypted_chat_key !== metadata.encrypted_chat_key) fail(409,'chat_key_resync_required');
        const existingMessage = await trx('messages').where({client_message_id:d.message_id}).first();
        if (existingMessage && existingMessage.chat_id !== d.chat_id) fail(409,'message_conflict');
        if (!chat) await trx('chats').insert({id:d.chat_id,hashed_user_id:deliveryScope.hashed_user_id,encrypted_title:metadata.encrypted_title,encrypted_category:metadata.encrypted_category,encrypted_chat_key:metadata.encrypted_chat_key,messages_v:1,title_v:1,created_at:current,updated_at:current,last_edited_overall_timestamp:current,last_message_timestamp:current,unread_count:1});
        else if (!existingMessage) await trx('chats').where({id:chat.id}).update({messages_v:Number(chat.messages_v || 0)+1,updated_at:current,last_edited_overall_timestamp:current,last_message_timestamp:current,unread_count:Number(chat.unread_count || 0)+1});
        if (!existingMessage) await trx('messages').insert({id:randomUUID(),client_message_id:d.message_id,chat_id:d.chat_id,hashed_user_id:deliveryScope.hashed_user_id,role:'assistant',encrypted_content:message.encrypted_content,encrypted_category:metadata.encrypted_category,created_at:current,updated_at:current});
      }
      if (!existing) {
        if (d.status !== 'delivery_pending' || d.revision !== 0) fail(409,'delivery_conflict');
        await trx('workflow_chat_deliveries').insert({id:randomUUID(),...d,revision:1});
      } else {
        // Retrying delivery creation returns the original ciphertext and stable IDs.
        if (d.revision === 0 && d.status === 'delivery_pending') return {delivery:existing};
        if (Number(existing.revision || 0) !== d.revision) fail(409,'delivery_conflict');
        if (['acknowledged','cancelled','expired'].includes(existing.status) && d.status !== existing.status) fail(409,'delivery_terminal');
        if (d.chat_id !== existing.chat_id || d.message_id !== existing.message_id || d.node_id !== existing.node_id) fail(409,'delivery_identity_conflict');
        if (d.status === 'acknowledged' && (!existing.client_persisted_at || d.claim_generation !== existing.claim_generation || d.claim_token_hash !== existing.claim_token_hash)) fail(409,'delivery_ack_not_persisted');
        await trx('workflow_chat_deliveries').where({id:existing.id}).update({...d,revision:d.revision+1});
      }
      // Durable ciphertext proves this is no longer an undelivered reservation.
      // Keep it non-expiring until the owner ACK closes delivery, or run deletion forgets it.
      if (d.client_persisted_at) await trx('workflow_delivery_history').where({...scope,run_id:runId,delivery_id:d.delivery_id,status:'reserved'}).update({expires_at:null});
      if (d.status === 'acknowledged') await trx('workflow_delivery_history').where({...scope,run_id:runId,delivery_id:d.delivery_id,status:'reserved'}).update({status:'delivered',delivered_at:current,expires_at:null});
      else if (['cancelled','expired'].includes(d.status) && !d.client_persisted_at) await trx('workflow_delivery_history').where({...scope,run_id:runId,delivery_id:d.delivery_id,status:'reserved'}).del();
      return {delivery:await trx('workflow_chat_deliveries').where({...deliveryScope,delivery_id:d.delivery_id}).first()};
    }
    fail(400,'unsupported_delivery_action');
  });
}
