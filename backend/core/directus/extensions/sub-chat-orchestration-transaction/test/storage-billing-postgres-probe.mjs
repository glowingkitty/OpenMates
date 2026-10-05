/*
 * Disposable actual-PostgreSQL proof for weekly personal storage billing.
 *
 * Run only inside the isolated Directus CI container. The runner supplies the
 * exact isolated API profile flags and BUILD_COMMIT_SHA as explicit exec env:
 *   node /directus/extensions/sub-chat-orchestration-transaction/test/storage-billing-postgres-probe.mjs <disposable-user-uuid> <expected-hashed-email>
 *
 * Every operation runs inside one outer transaction that is deliberately rolled
 * back. This checks the real extension SQL, locks, unique indexes and ledger
 * joins without changing the disposable user's durable balance or sending mail.
 * The opaque balance values test atomic CAS; numeric balance calculation is
 * covered by BillingService tests, since the server cannot decrypt user credit
 * ciphertext here.
 */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import process from 'node:process';
import { executeOperation } from '../src/operations.js';

const WEEK = 7 * 24 * 60 * 60;
const DAY = 24 * 60 * 60;
const FREE_BYTES = 1_073_741_824;
const START = Math.floor(Date.UTC(2025, 0, 5, 3) / 1000);
const ROLLBACK = Symbol('billing_probe_rollback');
let probeStage = 'isolated_setup';

function isolatedUserId() {
  const required = {
    OPENMATES_CI_ISOLATED: '1',
    OPENMATES_STORAGE_CAPACITY_FIXTURES: 'true',
    S3_ENDPOINT_URL: 'http://storage.ci.test:9000',
    SERVER_ENVIRONMENT: 'development',
  };
  for (const [key, value] of Object.entries(required)) {
    if (process.env[key] !== value) throw new Error('isolated_billing_profile_required');
  }
  if (process.env.DB_CLIENT !== 'pg' || process.env.DB_HOST !== 'cms-database'
    || process.env.DB_DATABASE !== 'openmates'
    || process.env.ADMIN_EMAIL !== 'runtime@example.com') {
    throw new Error('disposable_billing_database_required');
  }
  if (!/^[0-9a-f]{40}$/.test(process.env.BUILD_COMMIT_SHA || '')
    || !process.env.INTERNAL_API_SHARED_TOKEN) {
    throw new Error('isolated_billing_source_required');
  }
  const expectedHash = process.argv[3];
  if (!/^[A-Za-z0-9+/]{43}=$/.test(expectedHash || '')
    || Buffer.from(expectedHash, 'base64').toString('base64') !== expectedHash) {
    throw new Error('disposable_hashed_email_required');
  }
  const userId = process.argv[2];
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(userId || '')) {
    throw new Error('disposable_user_uuid_required');
  }
  return userId;
}

function request(userId, ownerHash, extra = {}) {
  return { protocol_version: 1, user_id: userId, hashed_user_id: ownerHash, ...extra };
}

function operation(db, name, userId, ownerHash, extra = {}, at = START) {
  probeStage = name;
  return executeOperation(db, name, request(userId, ownerHash, extra), new Date(at * 1000));
}

async function rejected(call, code) {
  await assert.rejects(call, (error) => {
    if (error?.code === code) return true;
    const actual = /^(?:storage|billing|stale|invalid)_[a-z0-9_]{1,65}$/.test(error?.code || '')
      ? error.code : 'unknown';
    throw new Error(`billing_probe_rejection_${actual}`);
  });
}

function periodPayload(ownerHash, periodStart, measuredBytes = FREE_BYTES + 1) {
  return {
    period_start_at: periodStart,
    measured_bytes: measuredBytes,
    credits_due: 3,
    charge_id: `storage:${ownerHash}:${periodStart}`,
    free_bytes: FREE_BYTES,
    credits_per_gib: 3,
    policy_version: 'storage-pg-proof-v1',
    source_version: 'logical-s3-v1',
    category_bytes: { legacy_uploads: measuredBytes },
  };
}

function dateAt(epoch) {
  return new Date(epoch * 1000).toISOString();
}

async function charge(db, userId, ownerHash, period, before, after, now) {
  const usageId = randomUUID();
  const payload = {
    charge_id: period.charge_id,
    app_id: 'system',
    skill_id: 'storage',
    requested_credits: period.credits_due,
    charged_credits: period.credits_due,
    expected_encrypted_balance: before,
    new_encrypted_balance: after,
    usage_entry: {
      id: usageId,
      charge_id: period.charge_id,
      user_id_hash: ownerHash,
      app_id: 'system',
      skill_id: 'storage',
      type: 'storage',
      source: 'direct',
      encrypted_credits_costs_total: 'ci-opaque-usage-ciphertext',
      created_at: now,
      updated_at: now,
    },
  };
  const first = await operation(db, 'commit_personal_charge', userId, ownerHash, payload, now);
  assert.equal(first.idempotent, false);
  assert.equal(first.charged_credits, period.credits_due);
  const replay = await operation(db, 'commit_personal_charge', userId, ownerHash, payload, now);
  assert.equal(replay.idempotent, true);
  assert.equal(replay.usage_id, usageId);
  assert.equal((await db('billing_charge_identities').where({ charge_id: period.charge_id })).length, 1);
  assert.equal((await db('usage').where({ charge_id: period.charge_id })).length, 1);
  assert.equal((await db('directus_users').where({ id: userId }).first()).encrypted_credit_balance, after);
  return usageId;
}

async function warningReceipt(db, userId, ownerHash, episodeId, stage, sentAt, acknowledgedAt,
                              advertisedAt) {
  const id = randomUUID();
  const key = `storage-billing-warning:${episodeId}:directus_user:${userId}:week-${stage}`;
  await db('email_deliveries').insert({
    id, delivery_key: key, email_type: `storage-billing-failed-${stage}`,
    campaign_key: episodeId, recipient_kind: 'directus_user', recipient_id: userId,
    stage: `week-${stage}`, status: 'processing',
    provider_message_id: `ci-rollback-message-${stage}`,
    provider_delivery_state: 'accepted',
    processing_started_at: dateAt(sentAt),
    metadata: JSON.stringify({ context: {
      deadline_date: dateAt(advertisedAt).slice(0, 10),
      unit_selection_hash: (await db('storage_billing_owner_state').where({id:ownerHash}).first()).selection_hash,
    } }),
  });
  const ack = () => operation(db, 'acknowledge_storage_warning', userId, ownerHash, {
    episode_id: episodeId, warning_stage: stage, delivery_id: id, now_at: acknowledgedAt,
  }, acknowledgedAt);
  await rejected(ack, 'storage_warning_not_delivered');
  await db('email_deliveries').where({ id }).update({ status: 'sent', sent_at: dateAt(sentAt) });
  await rejected(ack, 'storage_warning_not_delivered');
  await operation(db, 'record_storage_delivery_receipt', userId, ownerHash, {
    episode_id: episodeId, warning_stage: stage, delivery_id: id,
    message_id: `ci-rollback-message-${stage}`,
    state: 'delivered', observed_at: sentAt, now_at: acknowledgedAt,
  }, acknowledgedAt);
  assert.equal((await ack()).warning_count, stage);
  assert.equal((await ack()).idempotent, true);
  assert.ok((await db('email_deliveries').where({ id }).first()).storage_warning_acknowledged_at);
  return id;
}

async function prove(db, userId, ownerHash, originalBalance) {
  const firstPayload = periodPayload(ownerHash, START);
  const first = await operation(db, 'freeze_storage_period', userId, ownerHash, firstPayload);
  assert.equal(first.idempotent, false);
  const changedRetry = await operation(db, 'freeze_storage_period', userId, ownerHash,
    periodPayload(ownerHash, START, FREE_BYTES + 2));
  assert.equal(changedRetry.idempotent, true);
  assert.equal(Number(changedRetry.period.measured_bytes), FREE_BYTES + 1);
  assert.equal(changedRetry.period.policy_version, firstPayload.policy_version);
  await rejected(() => operation(db, 'mark_storage_period_paid', userId, ownerHash,
    { period_id: first.period.id }), 'storage_charge_not_fully_committed');
  assert.equal((await db('directus_users').where({ id: userId }).first()).encrypted_credit_balance,
    originalBalance);

  const balanceAfterFirst = `ci-rollback-balance-${randomUUID()}`;
  const firstUsageId = await charge(db, userId, ownerHash, first.period, originalBalance,
    balanceAfterFirst, START);
  assert.equal((await operation(db, 'mark_storage_period_paid', userId, ownerHash,
    { period_id: first.period.id })).all_debt_settled, true);
  assert.equal((await operation(db, 'mark_storage_period_paid', userId, ownerHash,
    { period_id: first.period.id })).idempotent, true);

  // A partial committed ledger row may exist after an old or faulty caller,
  // but it cannot settle this storage invoice or change the canonical balance.
  const partial = await operation(db, 'freeze_storage_period', userId, ownerHash,
    periodPayload(ownerHash, START + WEEK));
  probeStage = 'partial_ledger_fixture';
  await db('billing_charge_identities').insert({
    id: randomUUID(), charge_id: partial.period.charge_id, hashed_user_id: ownerHash,
    app_id: 'system', skill_id: 'storage', requested_credits: 3, charged_credits: 2,
    encrypted_balance_before: balanceAfterFirst, encrypted_balance_after: balanceAfterFirst,
    usage_id: randomUUID(), state: 'committed', created_at: dateAt(START), committed_at: dateAt(START),
  });
  await rejected(() => operation(db, 'mark_storage_period_paid', userId, ownerHash,
    { period_id: partial.period.id }), 'storage_charge_not_fully_committed');
  assert.equal((await db('directus_users').where({ id: userId }).first()).encrypted_credit_balance,
    balanceAfterFirst);
  assert.equal((await db('storage_billing_periods').where({ id: partial.period.id }).first()).state,
    'unpaid');

  // An uncertain receipt older than the provider retry window durably holds
  // warning progression and expiry. Roll its branch back to test delivered flow.
  const manualRollback = Symbol('manual_branch_rollback');
  try {
    await db.transaction(async (branch) => {
      const claim = await operation(branch, 'claim_storage_warning', userId, ownerHash,
        { now_at: START + WEEK }, START + WEEK);
      const id = randomUUID();
      await branch('email_deliveries').insert({
        id, delivery_key: `storage-billing-warning:${claim.episode_id}:directus_user:${userId}:week-1`,
        status: 'processing', processing_started_at: dateAt(START + WEEK - 601),
      });
      assert.equal((await operation(branch, 'mark_storage_warning_manual_review',
        userId, ownerHash, {
          episode_id: claim.episode_id, warning_stage: 1,
          delivery_id: id, now_at: START + WEEK,
        }, START + WEEK)).held, true);
      assert.equal((await operation(branch, 'claim_storage_warning', userId, ownerHash,
        { now_at: START + 2 * WEEK }, START + 2 * WEEK)).reason, 'manual_review');
      assert.equal((await operation(branch, 'inspect_storage_expiry', userId, ownerHash,
        { now_at: START + 5 * WEEK }, START + 5 * WEEK)).due, false);
      throw manualRollback;
    });
  } catch (error) {
    if (error !== manualRollback) throw error;
  }

  await db('storage_billing_owner_state').where({id:ownerHash}).update({
    selection_hash: 'ci-delivery-gate-fixed-selection',selection_at:START+WEEK,
  });
  let episodeId;
  const sentDays = [7, 16, 23, 34];
  const advertisedDay = 43;
  for (let stage = 1; stage <= 4; stage += 1) {
    const sentAt = START + sentDays[stage - 1] * DAY;
    const acknowledgedAt = stage === 1 ? sentAt + 8 * DAY : sentAt;
    const claim = await operation(db, 'claim_storage_warning', userId, ownerHash,
      { now_at: sentAt }, sentAt);
    assert.equal(claim.due, true);
    assert.equal(claim.warning_stage, stage);
    assert.equal(claim.episode_id, episodeId || claim.episode_id);
    episodeId = claim.episode_id;
    await warningReceipt(db, userId, ownerHash, episodeId, stage, sentAt,
      acknowledgedAt, START + advertisedDay * DAY);
    if (stage === 1) {
      assert.equal(Number((await db('storage_billing_owner_state')
        .where({ id: ownerHash }).first()).first_warning_at), sentAt);
    }
  }
  assert.equal((await operation(db, 'claim_storage_warning', userId, ownerHash,
    { now_at: START + 50 * DAY })).reason, 'four_delivered');
  assert.equal((await operation(db, 'inspect_storage_expiry', userId, ownerHash,
    { now_at: START + 42 * DAY })).due, false);
  assert.equal((await operation(db, 'inspect_storage_expiry', userId, ownerHash,
    { now_at: START + 43 * DAY })).due, true);

  const later = await operation(db, 'freeze_storage_period', userId, ownerHash,
    periodPayload(ownerHash, START + 2 * WEEK));
  const balanceAfterSecond = `ci-rollback-balance-${randomUUID()}`;
  const secondUsageId = await charge(db, userId, ownerHash, later.period,
    balanceAfterFirst, balanceAfterSecond, START + 2 * WEEK);
  const close = await operation(db, 'close_storage_billing_for_deleted_account',
    userId, ownerHash, {}, START + 50 * DAY);
  assert.equal(close.waived_count, 1);
  assert.equal(close.paid_count, 1);
  assert.equal((await operation(db, 'close_storage_billing_for_deleted_account',
    userId, ownerHash)).idempotent, true);
  assert.equal((await db('storage_billing_periods').where({ id: later.period.id }).first()).state,
    'paid');
  assert.equal((await db('storage_billing_periods').where({ id: partial.period.id }).first()).state,
    'waived');
  await rejected(() => operation(db, 'freeze_storage_period', userId, ownerHash,
    periodPayload(ownerHash, START + 3 * WEEK)), 'storage_owner_closed');
  assert.equal((await operation(db, 'claim_storage_warning', userId, ownerHash,
    { now_at: START + 60 * DAY })).reason, 'owner_closed');
  assert.equal((await operation(db, 'inspect_storage_expiry', userId, ownerHash,
    { now_at: START + 60 * DAY })).due, false);
  return {
    periodIds: [first.period.id, partial.period.id, later.period.id],
    chargeIds: [first.period.charge_id, partial.period.charge_id, later.period.charge_id],
    usageIds: [firstUsageId, secondUsageId],
    ownerHash,
  };
}

// A separate disposable owner exercises discovery, immutable membership and
// actual reference removal without depending on the caller's storage fixtures.
async function proveExpiry(db, originalBalance) {
  probeStage = 'expiry_fixture';
  const userId=randomUUID();const ownerHash=createHash('sha256').update(userId).digest('hex');
  const oldId=randomUUID();const newId=randomUUID();
  await db('directus_users').insert({id:userId,email:`ci-storage-expiry-pg-${userId}@example.com`,
    status:'active',encrypted_credit_balance:originalBalance});
  await db('upload_files').insert([
    {id:oldId,embed_id:randomUUID(),user_id:userId,created_at:START-86400,file_size_bytes:FREE_BYTES+64,
      files_metadata:JSON.stringify({original:{s3_key:`ci-expiry/${userId}/old.enc`}})},
    {id:newId,embed_id:randomUUID(),user_id:userId,created_at:START,file_size_bytes:64,
      files_metadata:JSON.stringify({original:{s3_key:`ci-expiry/${userId}/new.enc`}})},
  ]);
  const first=await operation(db,'freeze_storage_period',userId,ownerHash,periodPayload(ownerHash,START,FREE_BYTES+128));
  const frozen=await operation(db,'freeze_storage_warning_units',userId,ownerHash,{now_at:START});
  assert.equal(frozen.frozen,true);assert.equal(frozen.units.length,1);
  assert.equal(frozen.units[0].resource_id,oldId);assert.equal(frozen.units[0].kind,'upload');
  const replay=await operation(db,'freeze_storage_warning_units',userId,ownerHash,{now_at:START+DAY});
  assert.equal(replay.idempotent,true);assert.deepEqual(replay.units,frozen.units);
  const list=await operation(db,'list_storage_warning_units',userId,ownerHash,{limit:1});
  assert.deepEqual(list.units,frozen.units);assert.equal(list.has_more,false);
  const later=await operation(db,'freeze_storage_period',userId,ownerHash,periodPayload(ownerHash,START+WEEK));
  for(let stage=1;stage<=4;stage++) await warningReceipt(db,userId,ownerHash,frozen.episode_id,
    stage,START+(stage-1)*WEEK,START+(stage-1)*WEEK,START+4*WEEK);
  const payload={episode_id:frozen.episode_id,expected_encrypted_balance:originalBalance,
    regions:['nbg1','fsn1','hel1'],now_at:START+4*WEEK};
  await rejected(()=>operation(db,'apply_storage_expiry',userId,ownerHash,
    {...payload,expected_encrypted_balance:'ci-stale-topup'},START+4*WEEK),'stale_credit_balance');
  assert.equal((await db('upload_files').where({user_id:userId})).length,2);
  const ambiguousChat=randomUUID();const ambiguousRecovery=randomUUID();
  await db('chats').insert({id:ambiguousChat,hashed_user_id:ownerHash,hashed_team_id:null,
    created_at:START,updated_at:START,storage_state:'hot'});
  await db('chat_recovery_outputs').insert({id:ambiguousRecovery,root_chat_id:ambiguousChat,
    target_chat_id:ambiguousChat,turn_id:randomUUID(),hashed_user_id:ownerHash,
    preflight_id:randomUUID(),inference_task_id:randomUUID(),subject_id:'ci-expiry-ambiguous-output',
    output_kind:'message',output_version:1,chat_key_version:1,sealed_payload_digest:'0'.repeat(64),
    payload_size_bytes:128,state:'PENDING',payload_storage:'s3',payload_s3_key:null,deleted_at:null,
    created_at:dateAt(START)});
  await rejected(()=>operation(db,'apply_storage_expiry',userId,ownerHash,payload,START+4*WEEK),
    'storage_usage_incomplete');
  assert.equal((await db('upload_files').where({user_id:userId})).length,2);
  assert.equal((await db('storage_billing_periods').where({id:first.period.id}).first()).state,'unpaid');
  await db('chat_recovery_outputs').where({id:ambiguousRecovery}).delete();
  await db('chats').where({id:ambiguousChat}).delete();
  const applied=await operation(db,'apply_storage_expiry',userId,ownerHash,payload,START+4*WEEK);
  assert.equal(applied.applied,true);assert.equal(applied.after_bytes,64);
  assert.equal(applied.removed_bytes,FREE_BYTES+64);
  assert.deepEqual((await db('upload_files').where({user_id:userId})).map((row)=>row.id),[newId]);
  assert.equal((await db('storage_billing_periods').where({id:first.period.id}).first()).state,'waived_on_expiry');
  assert.equal((await db('storage_billing_periods').where({id:later.period.id}).first()).state,'unpaid');
  const tombstones=await db('storage_deletion_tombstones').whereIn('id',applied.tombstone_ids);
  assert.equal(tombstones.length,1);assert.equal(tombstones[0].state,'pending');
  assert.deepEqual(tombstones[0].purge_states,{'1':{nbg1:'pending',fsn1:'pending',hel1:'pending'}});
  const topupBalance=`ci-expiry-topup-${randomUUID()}`;
  await db('directus_users').where({id:userId}).update({encrypted_credit_balance:topupBalance});
  await rejected(()=>charge(db,userId,ownerHash,first.period,topupBalance,'ci-stale-storage-debit',START+4*WEEK),
    'storage_period_not_chargeable');
  assert.equal((await db('directus_users').where({id:userId}).first()).encrypted_credit_balance,topupBalance);
  assert.equal((await db('billing_charge_identities').where({charge_id:first.period.charge_id})).length,0);
  assert.equal((await db('usage').where({charge_id:first.period.charge_id})).length,0);
  await rejected(()=>operation(db,'mark_storage_period_paid',userId,ownerHash,{period_id:first.period.id}),
    'storage_period_not_chargeable');
  await rejected(()=>operation(db,'create_or_reuse_pending_settlement',userId,ownerHash,{
    charge_id:first.period.charge_id,vault_key_id:'ci-expiry-key',
    encrypted_settlement_payload:'ci-stale-expiry-payload',
    settlement_payload_hash:'a'.repeat(64),retryable_error_code:'ci_retry',
  }),'storage_period_not_chargeable');
  assert.equal((await db('billing_settlement_outbox').where({charge_id:first.period.charge_id})).length,0);

  const owner=await db('storage_billing_owner_state').where({id:ownerHash}).first();
  assert.equal(owner.warning_count,0);assert.equal(owner.episode_id,null);
  await db('storage_billing_owner_state').where({id:ownerHash}).update({expiry_audit:null,episode_id:randomUUID()});
  const appliedAgain=await operation(db,'apply_storage_expiry',userId,ownerHash,payload,START+4*WEEK);
  assert.equal(appliedAgain.idempotent,true);assert.deepEqual(appliedAgain.removed_row_ids,applied.removed_row_ids);
  return {userId,ownerHash,unitIds:frozen.units.map((unit)=>unit.unit_id),tombstoneIds:applied.tombstone_ids};
}

async function main() {
  const userId = isolatedUserId();
  const ownerHash = createHash('sha256').update(userId).digest('hex');
  const runtimeRequire = createRequire(realpathSync('/directus/node_modules/@directus/api/package.json'));
  const knex = runtimeRequire('knex');
  const db = knex({
    client: 'pg',
    connection: {
      host: process.env.DB_HOST,
      port: Number(process.env.DB_PORT || 5432),
      database: process.env.DB_DATABASE,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
    },
    pool: { min: 0, max: 1 },
  });
  let proof;let expiryProof;
  try {
    const baseline = await db('directus_users').where({ id: userId })
      .select('id', 'email', 'hashed_email', 'encrypted_credit_balance').first();
    if (!baseline || baseline.hashed_email !== process.argv[3]
      || baseline.email !== process.argv[3].slice(0, 64) + '@example.com'
      || typeof baseline.encrypted_credit_balance !== 'string'
      || baseline.encrypted_credit_balance.length < 8) {
      throw new Error('disposable_ci_billing_user_required');
    }
    if (await db('storage_billing_owner_state').where({ id: ownerHash }).first()) {
      throw new Error('disposable_ci_billing_owner_not_fresh');
    }
    try {
      await db.transaction(async (trx) => {
        await trx.raw("SET LOCAL lock_timeout = '2s'");
        await trx.raw("SET LOCAL statement_timeout = '15s'");
        const locked = await trx('directus_users').where({ id: userId }).forUpdate().first();
        if (locked.encrypted_credit_balance !== baseline.encrypted_credit_balance) {
          throw new Error('disposable_ci_billing_balance_changed');
        }
        proof = await prove(trx, userId, ownerHash, baseline.encrypted_credit_balance);
        expiryProof = await proveExpiry(trx, baseline.encrypted_credit_balance);
        throw ROLLBACK;
      });
    } catch (error) {
      if (error !== ROLLBACK) throw error;
    }
    if (!proof || !expiryProof) throw new Error('billing_pg_proof_incomplete');
    assert.equal(await db('directus_users').where({id:expiryProof.userId}).first(),undefined);
    assert.equal((await db('storage_billing_warning_units').where({hashed_user_id:expiryProof.ownerHash})).length,0);
    assert.equal((await db('storage_deletion_tombstones').whereIn('id',expiryProof.tombstoneIds)).length,0);
    const after = await db('directus_users').where({ id: userId })
      .select('encrypted_credit_balance').first();
    assert.equal(after.encrypted_credit_balance, baseline.encrypted_credit_balance);
    assert.equal((await db('storage_billing_periods').whereIn('id', proof.periodIds)).length, 0);
    assert.equal((await db('billing_charge_identities').whereIn('charge_id', proof.chargeIds)).length, 0);
    assert.equal((await db('usage').whereIn('id', proof.usageIds)).length, 0);
    assert.equal((await db('storage_billing_owner_state').where({ id: ownerHash })).length, 0);
    process.stdout.write(JSON.stringify({
      passed: true, frozen_snapshot: true, exact_ledger_replay: true,
      partial_invoice_unpaid: true, four_delivered_warning_gates: true,
      manual_hold: true, deleted_owner_closed: true, rollback_verified: true,
      immutable_selected_units:true,actual_expiry_transaction:true,exact_warned_waiver:true,regional_purge_outbox:true,expiry_audit_replay:true,
    }) + '\n');
  } finally {
    await db.destroy();
  }
}

main().catch((error) => {
  const raw = String(error?.code || error?.message || 'unknown');
  const safe = /^[0-9]{5}$/.test(raw) ? `sql_${raw}`
    : /^(ERR_[A-Z0-9_]+|(?:storage|billing|isolated|disposable)_[a-z0-9_]{1,100})$/.test(raw)
      ? raw.toLowerCase() : 'probe_failed';
  const line = String(error?.stack || '').match(/storage-billing-postgres-probe[.]mjs:([0-9]+):/);
  process.stderr.write(`storage_billing_pg_probe_failed:${safe}_during_${probeStage}${line ? '_at_' + line[1] : ''}\n`);
  process.exitCode = 1;
});
