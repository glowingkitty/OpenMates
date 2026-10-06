/* Transaction contracts for frozen weekly storage charges and delivered warnings. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { executeOperation, SubChatOrchestrationError, testing } from '../src/operations.js';

const USER = '22222222-2222-4222-8222-222222222222';
const OWNER = createHash('sha256').update(USER).digest('hex');
const START = 1791082800;
const WEEK = 604800;
const TEAM = 'b'.repeat(64);

function db(seed = {}) {
  const rows = structuredClone({ storage_billing_owner_state: [{
    id: OWNER,user_id: USER,episode_id:null,warning_count:0,first_warning_at:null,last_warning_at:null,
    deadline_at:null,advertised_not_before_at:null,closed_at:null,warning_manual_review_at:null,
    selection_hash:'test-selected-unit-hash',selection_at:START,selected_bytes:1073741825,
    warned_period_ids:[],updated_at:new Date(START*1000),
  }], ...seed });
  const client = (table) => {
    const predicates = [];
    let sorter;
    let max;
    const matching = () => {
      let found = (rows[table] || []).filter((row) => predicates.every((fn) => fn(row)));
      if (sorter) found = found.sort(sorter);
      return max == null ? found : found.slice(0, max);
    };
    const q = {
      where(fields, operator, expected) {
        if (typeof fields === 'string') {
          predicates.push((row) => operator === '>' ? row[fields] > expected
            : operator === '>=' ? new Date(row[fields]) >= new Date(expected) : row[fields] === expected);
          return q;
        }
        predicates.push((row) => Object.entries(fields).every(([key, value]) => row[key] === value));
        return q;
      },
      whereIn(field, values) {
        predicates.push((row) => values.includes(row[field]));
        return q;
      },
      forUpdate() { return q; },
      forShare() { return q; },
      orderBy(field, direction) {
        sorter = (a, b) => (a[field] < b[field] ? -1 : a[field] > b[field] ? 1 : 0)
          * (direction === 'desc' ? -1 : 1);
        return q;
      },
      limit(n) { max = n; return q; },
      async first() { return matching()[0]; },
      async insert(value) {
        rows[table] ||= [];
        rows[table].push(structuredClone(value));
        return 1;
      },
      async delete() {
        const found=matching();rows[table]=(rows[table]||[]).filter((row)=>!found.includes(row));return found.length;
      },
      async update(values) {
        const found = matching();
        found.forEach((row) => Object.assign(row, structuredClone(values)));
        return found.length;
      },
      sum(fields) {
        const [alias, column] = Object.entries(fields)[0];
        return { first: async () => ({
          [alias]: matching().reduce((n, row) => n + Number(row[column]), 0),
        }) };
      },
      then(resolve, reject) { return Promise.resolve(matching()).then(resolve, reject); },
    };
    return q;
  };
  client.raw = async (sql,bindings) => {
    client.rawCalls ||= [];client.rawCalls.push({sql,bindings});
    if(sql.includes('FROM billing_settlement_outbox')) return {rows:(rows.billing_settlement_outbox||[]).filter((o)=>['pending','retry_scheduled','manual_review'].includes(o.state))};
    if (sql.includes('WITH requested AS')) return {rows:[{owner_kind:'personal',owner_id:USER,
      measurement_at:START,categories:{legacy_uploads:String((rows.upload_files||[]).reduce((sum,u)=>sum+u.file_size_bytes,0))},incomplete:false}]};
    if (sql.includes('WITH scope AS')) return {rows:(rows.upload_files||[]).map((u)=>({kind:'independent_upload',
      resource_id:u.id,oldest_at:u.created_at,bytes:u.file_size_bytes,
      rows:[{collection:'upload_files',id:u.id,fingerprint:u.fingerprint||'canonical-row-hash'}],
      objects:[{logical_bucket:'chatfiles',object_key:u.files_metadata.original.s3_key}]}))};
    if (sql.includes('WITH requested_objects AS')) return {rows:[{refs:(rows.upload_files||[]).map((u)=>({
      collection:'upload_files',id:u.id,bucket:'chatfiles',object_key:u.files_metadata.original.s3_key})),ambiguous:false}]};
    return {rows:[]};
  };
  client.transaction = async (callback) => {
    const snapshot=structuredClone(rows);
    try {return await callback(client);} catch(error) {
      for(const key of Object.keys(rows)) delete rows[key];Object.assign(rows,snapshot);throw error;
    }
  };
  client.rows = rows;
  return client;
}

const request = (extra = {}) => ({
  protocol_version: 1, user_id: USER, hashed_user_id: OWNER, ...extra,
});

const freeze = (database, measured = 1_073_741_825) => executeOperation(
  database, 'freeze_storage_period', request({
    period_start_at: START, measured_bytes: measured, credits_due: 3,
    charge_id: `storage:${OWNER}:${START}`, free_bytes: 1_073_741_824,
    credits_per_gib: 3, policy_version: 'storage-v2',
    source_version: 'logical-s3-v1', category_bytes: { uploads: measured },
  }), new Date(START * 1000),
);

const teamRequest = (extra = {}) => ({ protocol_version: 1, hashed_team_id: TEAM, ...extra });
const teamDb = (balance = 0) => db({
  teams: [{ id: '33333333-3333-4333-8333-333333333333', hashed_team_id: TEAM, status: 'active' }],
  team_credit_accounts: [{ id: '44444444-4444-4444-8444-444444444444', hashed_team_id: TEAM,
    balance_credits: balance, version: 1, encrypted_balance: 'opaque-client-snapshot' }],
  team_credit_events: [], team_usage_events: [],
});
const freezeTeam = (database, periodStart = START) => executeOperation(database,
  'freeze_team_storage_period', teamRequest({
    period_start_at: periodStart, measured_bytes: 1_073_741_825, credits_due: 3,
    charge_id: `team-storage:${TEAM}:${periodStart}`, free_bytes: 1_073_741_824,
    credits_per_gib: 3, policy_version: 'team-storage-1gb-3credits-week-v1',
    source_version: 'logical-s3-v1', category_bytes: { chat_pages: 1_073_741_825 },
  }), new Date(periodStart * 1000));

// contract-test: supporting surface=rest_api assertions=billing.storage.team-warning-expiry
test('unresolved Team notice contact has a durable retryable hold status', async () => {
  const database = teamDb();
  const episode = '55555555-5555-4555-8555-555555555555';
  database.rows.team_storage_billing_owner_state = [{ id: TEAM, owner_kind: 'team',
    hashed_team_id: TEAM, episode_id: episode, warning_count: 0,
    warning_manual_review_at: null, warning_manual_review_reason: null }];
  const set = (reason) => executeOperation(database, 'set_team_storage_notice_hold',
    teamRequest({ episode_id: episode, reason }), new Date(START * 1000));
  assert.equal((await set('recipient_contact_unavailable')).held, true);
  assert.equal(database.rows.team_storage_billing_owner_state[0].warning_manual_review_reason,
    'recipient_contact_unavailable');
  assert.equal(database.rows.team_storage_billing_owner_state[0].warning_manual_review_at, null);
  assert.equal((await set(null)).held, false);
  assert.equal(database.rows.team_storage_billing_owner_state[0].warning_manual_review_reason, null);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.team-policy-gate,billing.storage.exact-settlement
test('Team Sunday invoice debits only the Team wallet once with SYSTEM attribution', async () => {
  const database = teamDb(6);
  const { period } = await freezeTeam(database);
  const retry = await freezeTeam(database);
  assert.equal(retry.idempotent, true);
  assert.equal(database.rows.team_storage_billing_periods.length, 1);
  const charge = () => executeOperation(database, 'commit_team_storage_charge', teamRequest({
    period_id: period.id, expected_version: 1, occurred_at: START,
  }), new Date(START * 1000));
  const paid = await charge();
  assert.equal(paid.state, 'paid');
  assert.equal(paid.charged_credits, 3);
  assert.equal(database.rows.team_credit_accounts[0].balance_credits, 3);
  assert.equal(database.rows.team_credit_accounts[0].version, 2);
  assert.equal(database.rows.team_credit_accounts[0].encrypted_balance, 'opaque-client-snapshot');
  assert.equal(database.rows.team_credit_events[0].event_id, period.charge_id);
  assert.equal(database.rows.team_credit_events[0].event_type, 'deduction');
  assert.equal(database.rows.team_credit_events[0].amount, -3);
  assert.equal(database.rows.team_credit_events[0].actor_user_hash,
    createHash('sha256').update('system:team-storage').digest('hex'));
  assert.equal(database.rows.team_usage_events[0].workspace_type, 'team_storage');
  const duplicate = await charge();
  assert.equal(duplicate.idempotent, true);
  assert.equal(database.rows.team_credit_events.length, 1);
  assert.equal(database.rows.team_credit_accounts[0].balance_credits, 3);
  assert.equal(database.rows.storage_billing_periods, undefined);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.team-policy-gate,billing.storage.exact-settlement
test('Team storage debit holds on insufficient, negative, and stale version; top-up retry pays once', async () => {
  const database = teamDb(0);
  const { period } = await freezeTeam(database);
  const charge = (version) => executeOperation(database, 'commit_team_storage_charge', teamRequest({
    period_id: period.id, expected_version: version, occurred_at: START,
  }), new Date(START * 1000));
  await assert.rejects(charge(1), { code: 'insufficient_team_credits' });
  assert.equal(database.rows.team_credit_accounts[0].balance_credits, 0);
  assert.equal(database.rows.team_storage_billing_periods[0].state, 'unpaid');
  database.rows.team_credit_accounts[0].balance_credits = -1;
  await assert.rejects(charge(1), { code: 'insufficient_team_credits' });
  database.rows.team_credit_accounts[0].balance_credits = 5;
  database.rows.team_credit_accounts[0].version = 2;
  await assert.rejects(charge(1), { code: 'stale_team_credit_balance' });
  assert.equal(database.rows.team_credit_events.length, 0);
  await charge(2);
  assert.equal(database.rows.team_credit_accounts[0].balance_credits, 2);
  assert.equal(database.rows.team_credit_accounts[0].version, 3);
  assert.equal(database.rows.team_credit_events.length, 1);
  await assert.rejects(executeOperation(database, 'commit_team_charge', {
    protocol_version: 1, event_id: period.charge_id, hashed_team_id: TEAM,
    actor_user_hash: OWNER, credits: 3, expected_version: 3,
    encrypted_balance: 'opaque', workspace_type: 'chat', occurred_at: START,
  }), { code: 'reserved_team_storage_charge' });
});

// contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote,billing.storage.exact-settlement
test('weekly snapshot is immutable and a changed retry reuses the original charge', async () => {
  const database = db();
  const first = await freeze(database);
  const retry = await freeze(database, 1_073_741_826);
  assert.equal(first.idempotent, false);
  assert.equal(retry.idempotent, true);
  assert.equal(retry.period.measured_bytes, 1_073_741_825);
  assert.equal(database.rows.storage_billing_periods.length, 1);
  await assert.rejects(
    executeOperation(database, 'freeze_storage_period', request({
      period_start_at: START, measured_bytes: 1_073_741_825, credits_due: 2,
      charge_id: `storage:${OWNER}:${START}`, free_bytes: 1_073_741_824,
      credits_per_gib: 3, policy_version: 'storage-v2',
      source_version: 'logical-s3-v1', category_bytes: {},
    })),
    (error) => error instanceof SubChatOrchestrationError && error.code === 'storage_quote_mismatch',
  );
});

// contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement
test('a partial or pending ledger charge cannot mark the invoice paid', async () => {
  const database = db();
  const { period } = await freeze(database);
  database.rows.billing_charge_identities = [{
    charge_id: period.charge_id, hashed_user_id: OWNER, app_id: 'system',
    skill_id: 'storage', requested_credits: 3, charged_credits: 2,
    state: 'committed',
  }];
  const mark = () => executeOperation(database, 'mark_storage_period_paid',
    request({ period_id: period.id }));
  await assert.rejects(mark(), (error) => error.code === 'storage_charge_not_fully_committed');
  assert.equal(period.state, 'unpaid');
  database.rows.billing_charge_identities[0].charged_credits = 3;
  database.rows.billing_charge_identities[0].state = 'retry_scheduled';
  await assert.rejects(mark(), (error) => error.code === 'storage_charge_not_fully_committed');
  database.rows.billing_charge_identities[0].state = 'committed';
  const paid = await mark();
  assert.equal(paid.state, 'paid');
  assert.equal(database.rows.storage_billing_periods[0].state, 'paid');
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('four delivered owner warnings require weekly spacing and day-28 expiry', async () => {
  const database = db();
  await freeze(database);
  let episode;
  for (let stage = 1; stage <= 4; stage++) {
    const at = START + (stage - 1) * WEEK;
    const warning = await executeOperation(database, 'claim_storage_warning',
      request({ now_at: at }), new Date(at * 1000));
    assert.equal(warning.warning_stage, stage);
    assert.equal(warning.outstanding_credits, 3);
    episode = warning.episode_id;
    const deliveryId = `33333333-3333-4333-8333-33333333333${stage}`;
    database.rows.email_deliveries ||= [];
    database.rows.email_deliveries.push({
      id: deliveryId,
      delivery_key: `storage-billing-warning:${episode}:directus_user:${USER}:week-${stage}`,
      status: 'processing',
      provider_message_id: `ci-provider-${stage}`,
      provider_delivery_state: 'accepted',
      metadata: { context: { unit_selection_hash: 'test-selected-unit-hash', deadline_date: new Date((START + 29 * 86400) * 1000).toISOString().slice(0, 10) } },
    });
    const ack = () => executeOperation(database, 'acknowledge_storage_warning',
      request({ episode_id: episode, warning_stage: stage, delivery_id: deliveryId, now_at: at }),
      new Date(at * 1000));
    await assert.rejects(ack(), (error) => error.code === 'storage_warning_not_delivered');
    database.rows.email_deliveries.at(-1).status = 'sent';
    database.rows.email_deliveries.at(-1).sent_at = new Date(at * 1000).toISOString();
    await assert.rejects(ack(), (error) => error.code === 'storage_warning_not_delivered');
    await executeOperation(database, 'record_storage_delivery_receipt',
      request({ episode_id: episode, warning_stage: stage, delivery_id: deliveryId,
        message_id: `ci-provider-${stage}`, state: 'delivered',
        observed_at: at, now_at: at }), new Date(at * 1000));
    const recorded = await ack();
    assert.equal(recorded.warning_count, stage);
    assert.ok(database.rows.email_deliveries.at(-1).storage_warning_acknowledged_at);
    assert.equal((await ack()).idempotent, true);
    const tooSoon = await executeOperation(database, 'claim_storage_warning',
      request({ now_at: at + WEEK - 1 }));
    assert.equal(tooSoon.due, false);
  }
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 4 * WEEK - 1 }))).due, false);
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 4 * WEEK }))).due, false);
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 29 * 86400 }))).due, true);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.expiry-invoice-closure,billing.storage.exact-settlement
test('account deletion waives only unpaid invoices and permanently closes future billing', async () => {
  const database = db();
  const { period } = await freeze(database);
  database.rows.directus_users = [{ id: USER }];
  const paid = { ...period, id: 'p'.repeat(64), charge_id: 'old', state: 'paid' };
  database.rows.storage_billing_periods.push(paid);
  const committed = { ...period, id: 'c'.repeat(64), charge_id: 'committed-old', state: 'unpaid' };
  database.rows.storage_billing_periods.push(committed);
  database.rows.billing_charge_identities = [{
    charge_id: committed.charge_id, hashed_user_id: OWNER, app_id: 'system',
    skill_id: 'storage', requested_credits: 3, charged_credits: 3, state: 'committed',
  }];
  const close = () => executeOperation(database,
    'close_storage_billing_for_deleted_account', request());
  assert.equal((await close()).waived_count, 1);
  assert.equal((await close()).idempotent, true);
  assert.equal(database.rows.storage_billing_periods[0].state, 'waived');
  assert.equal(paid.state, 'paid');
  assert.equal(committed.state, 'paid');
  await assert.rejects(freeze(database), (error) => error.code === 'storage_owner_closed');
  assert.equal((await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START + WEEK }))).due, false);
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 4 * WEEK }))).due, false);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('expired uncertain provider receipt enters durable manual hold and blocks expiry', async () => {
  const database = db();
  await freeze(database);
  const warning = await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START }), new Date(START * 1000));
  const deliveryId = '44444444-4444-4444-8444-444444444444';
  database.rows.email_deliveries = [{
    id: deliveryId,
    delivery_key: `storage-billing-warning:${warning.episode_id}:directus_user:${USER}:week-1`,
    status: 'processing', processing_started_at: new Date((START - 601) * 1000).toISOString(),
  }];
  const held = await executeOperation(database, 'mark_storage_warning_manual_review',
    request({ episode_id: warning.episode_id, warning_stage: 1,
      delivery_id: deliveryId, now_at: START }), new Date(START * 1000));
  assert.equal(held.held, true);
  assert.equal(database.rows.email_deliveries[0].status, 'manual_review');
  assert.equal((await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START + WEEK }))).reason, 'manual_review');
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 5 * WEEK }))).due, false);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('late fourth receipt moves the advertised deadline and delayed ack keeps actual first send', async () => {
  const database = db();
  await freeze(database);
  let episode;
  for (let stage = 1; stage <= 4; stage++) {
    const sentAt = stage === 4 ? START + 27 * 86400 : START + (stage - 1) * WEEK;
    const ackAt = stage === 1 ? sentAt + WEEK : sentAt;
    const warning = await executeOperation(database, 'claim_storage_warning',
      request({ now_at: sentAt }), new Date(sentAt * 1000));
    episode = warning.episode_id;
    const deliveryId = `55555555-5555-4555-8555-55555555555${stage}`;
    const deadlineDay = stage === 4 ? 35 : 29;
    database.rows.email_deliveries ||= [];
    database.rows.email_deliveries.push({
      id: deliveryId, status: 'sent',
      provider_message_id: `ci-late-${stage}`,
      provider_delivery_state: 'accepted',
      delivery_key: `storage-billing-warning:${episode}:directus_user:${USER}:week-${stage}`,
      sent_at: new Date(sentAt * 1000).toISOString(),
      metadata: { context: {
        unit_selection_hash: 'test-selected-unit-hash', deadline_date: new Date((START + deadlineDay * 86400) * 1000).toISOString().slice(0, 10),
      } },
    });
    await executeOperation(database, 'record_storage_delivery_receipt',
      request({ episode_id: episode, warning_stage: stage, delivery_id: deliveryId,
        message_id: `ci-late-${stage}`, state: 'delivered',
        observed_at: sentAt, now_at: ackAt }), new Date(ackAt * 1000));
    await executeOperation(database, 'acknowledge_storage_warning',
      request({ episode_id: episode, warning_stage: stage,
        delivery_id: deliveryId, now_at: ackAt }), new Date(ackAt * 1000));
    if (stage === 1) {
      assert.equal(database.rows.storage_billing_owner_state[0].first_warning_at, START);
    }
  }
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 34 * 86400 }))).due, false);
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 35 * 86400 }))).due, true);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('UTC midnight-crossing delivery keeps the advertised calendar date valid', async () => {
  const database = db();
  await freeze(database);
  const warning = await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START }), new Date(START * 1000));
  const sentAt = START + 21 * 3600 + 60; // 00:01 UTC on the next day
  const deliveryId = '66666666-6666-4666-8666-666666666666';
  database.rows.email_deliveries = [{
    id: deliveryId, status: 'sent',
    provider_message_id: 'ci-midnight',
    provider_delivery_state: 'accepted',
    delivery_key: `storage-billing-warning:${warning.episode_id}:directus_user:${USER}:week-1`,
    sent_at: new Date(sentAt * 1000).toISOString(),
    metadata: { context: {
      unit_selection_hash: 'test-selected-unit-hash', deadline_date: new Date((START + 29 * 86400) * 1000).toISOString().slice(0, 10),
    } },
  }];
  await executeOperation(database, 'record_storage_delivery_receipt',
    request({ episode_id: warning.episode_id, warning_stage: 1, delivery_id: deliveryId,
      message_id: 'ci-midnight', state: 'delivered',
      observed_at: sentAt, now_at: sentAt }), new Date(sentAt * 1000));
  const ack = await executeOperation(database, 'acknowledge_storage_warning',
    request({ episode_id: warning.episode_id, warning_stage: 1,
      delivery_id: deliveryId, now_at: sentAt }), new Date(sentAt * 1000));
  assert.equal(ack.first_warning_at, sentAt);
  assert.equal(ack.deadline_at, sentAt + 4 * WEEK);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('accepted submission cannot count; a late bounce holds expiry after four ACKs', async () => {
  const database = db();
  await freeze(database);
  let firstId;
  let episode;
  for (let stage = 1; stage <= 4; stage++) {
    const at = START + (stage - 1) * WEEK;
    const claim = await executeOperation(database, 'claim_storage_warning',
      request({ now_at: at }), new Date(at * 1000));
    episode = claim.episode_id;
    const id = `77777777-7777-4777-8777-77777777777${stage}`;
    if (stage === 1) firstId = id;
    database.rows.email_deliveries ||= [];
    database.rows.email_deliveries.push({
      id, delivery_key: `storage-billing-warning:${episode}:directus_user:${USER}:week-${stage}`,
      status: 'sent', sent_at: new Date(at * 1000).toISOString(),
      provider_message_id: `provider-${stage}`, provider_delivery_state: 'accepted',
      metadata: { context: { unit_selection_hash: 'test-selected-unit-hash', deadline_date: new Date((START + 29 * 86400) * 1000).toISOString().slice(0, 10) } },
    });
    const ack = () => executeOperation(database, 'acknowledge_storage_warning',
      request({ episode_id: episode, warning_stage: stage, delivery_id: id, now_at: at }),
      new Date(at * 1000));
    await assert.rejects(ack(), (error) => error.code === 'storage_warning_not_delivered');
    assert.equal(database.rows.storage_billing_owner_state[0].warning_count, stage - 1);
    await assert.rejects(
      executeOperation(database, 'record_storage_delivery_receipt',
        request({ episode_id: episode, warning_stage: stage, delivery_id: id,
          message_id: 'wrong-provider-id', state: 'delivered',
          observed_at: at, now_at: at }), new Date(at * 1000)),
      (error) => error.code === 'storage_delivery_identity_mismatch',
    );
    await assert.rejects(
      executeOperation(database, 'record_storage_delivery_receipt',
        request({ episode_id: episode, warning_stage: stage, delivery_id: id,
          message_id: `provider-${stage}`, state: 'delivered',
          observed_at: at - 120, now_at: at }), new Date(at * 1000)),
      (error) => error.code === 'storage_delivery_event_before_submission',
    );
    await executeOperation(database, 'record_storage_delivery_receipt',
      request({ episode_id: episode, warning_stage: stage, delivery_id: id,
        message_id: `provider-${stage}`, state: 'delivered', observed_at: at, now_at: at }),
      new Date(at * 1000));
    await ack();
  }
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 29 * 86400 }))).due, true);
  const bounce = await executeOperation(database, 'record_storage_delivery_receipt',
    request({ episode_id: episode, warning_stage: 1, delivery_id: firstId,
      message_id: 'provider-1', state: 'failed', observed_at: START + 29 * 86400,
      now_at: START + 29 * 86400 }), new Date((START + 29 * 86400) * 1000));
  assert.equal(bounce.held, true);
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: START + 40 * 86400 }))).due, false);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('delivery two days after submission counts and extends the owner clock', async () => {
  const database = db();
  await freeze(database);
  const claim = await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START }), new Date(START * 1000));
  const id = '88888888-8888-4888-8888-888888888888';
  database.rows.email_deliveries = [{
    id, delivery_key: `storage-billing-warning:${claim.episode_id}:directus_user:${USER}:week-1`,
    status: 'sent', sent_at: new Date(START * 1000).toISOString(),
    provider_message_id: 'provider-delayed', provider_delivery_state: 'accepted',
    metadata: { context: { unit_selection_hash: 'test-selected-unit-hash', deadline_date: new Date((START + 29 * 86400) * 1000).toISOString().slice(0, 10) } },
  }];
  const deliveredAt = START + 2 * 86400;
  await executeOperation(database, 'record_storage_delivery_receipt',
    request({ episode_id: claim.episode_id, warning_stage: 1, delivery_id: id,
      message_id: 'provider-delayed', state: 'delivered',
      observed_at: deliveredAt, now_at: deliveredAt }), new Date(deliveredAt * 1000));
  const ack = await executeOperation(database, 'acknowledge_storage_warning',
    request({ episode_id: claim.episode_id, warning_stage: 1,
      delivery_id: id, now_at: deliveredAt }), new Date(deliveredAt * 1000));
  assert.equal(ack.warning_count, 1);
  assert.equal(ack.first_warning_at, deliveredAt);
  assert.equal(ack.deadline_at, deliveredAt + 4 * WEEK);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
test('accepted notice past the 90-day event horizon enters manual hold', async () => {
  const database = db();
  await freeze(database);
  const claim = await executeOperation(database, 'claim_storage_warning',
    request({ now_at: START }), new Date(START * 1000));
  const id = '99999999-9999-4999-8999-999999999999';
  database.rows.email_deliveries = [{
    id, delivery_key: `storage-billing-warning:${claim.episode_id}:directus_user:${USER}:week-1`,
    status: 'sent', provider_delivery_state: 'accepted',
    provider_message_id: 'old-provider-id',
    processing_started_at: new Date(START * 1000).toISOString(),
  }];
  const nowAt = START + 90 * 86400;
  const hold = await executeOperation(database, 'mark_storage_warning_manual_review',
    request({ episode_id: claim.episode_id, warning_stage: 1,
      delivery_id: id, now_at: nowAt }), new Date(nowAt * 1000));
  assert.equal(hold.held, true);
  assert.equal(hold.reason, 'provider_delivery_unverified');
  assert.equal((await executeOperation(database, 'inspect_storage_expiry',
    request({ now_at: nowAt + WEEK }))).due, false);
});


const OLD_UPLOAD='77777777-7777-4777-8777-777777777777';
const NEW_UPLOAD='88888888-8888-4888-8888-888888888888';
function expiryDb() {
  const database=db({directus_users:[{id:USER,encrypted_credit_balance:'opaque-expiry-balance'}],
    upload_files:[{id:OLD_UPLOAD,user_id:USER,created_at:START-86400,file_size_bytes:1073741888,
      files_metadata:{original:{s3_key:'old.enc'}}},
      {id:NEW_UPLOAD,user_id:USER,created_at:START,file_size_bytes:64,
      files_metadata:{original:{s3_key:'new.enc'}}}]});
  Object.assign(database.rows.storage_billing_owner_state[0],{selection_hash:null,selection_at:null,
    selected_bytes:null,warned_period_ids:null});
  return database;
}
async function deliveredExpiry(database) {
  const period=(await freeze(database)).period;
  const frozen=await executeOperation(database,'freeze_storage_warning_units',request({now_at:START}));
  for(let stage=1;stage<=4;stage++) {
    const at=START+(stage-1)*WEEK;
    const deliveryId=`66666666-6666-4666-8666-66666666666${stage}`;
    database.rows.email_deliveries ||= [];
    database.rows.email_deliveries.push({id:deliveryId,
      delivery_key:`storage-billing-warning:${frozen.episode_id}:directus_user:${USER}:week-${stage}`,
      status:'sent',provider_delivery_state:'delivered',provider_delivered_at:new Date(at*1000).toISOString(),
      metadata:{context:{unit_selection_hash:frozen.unit_selection_hash,
        deadline_date:new Date((START+4*WEEK)*1000).toISOString().slice(0,10)}}});
    await executeOperation(database,'acknowledge_storage_warning',request({episode_id:frozen.episode_id,
      warning_stage:stage,delivery_id:deliveryId,now_at:at}),new Date(at*1000));
  }
  return {frozen,period};
}
const expiryRequest=(episodeId,extra={})=>request({episode_id:episodeId,
  expected_encrypted_balance:'opaque-expiry-balance',regions:['nbg1','fsn1','hel1'],now_at:START+4*WEEK,...extra});

// contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection,billing.storage.weekly-quote
test('freezes only oldest complete units and preserves the exact selection on retry',async()=>{
  const database=expiryDb();await freeze(database);
  const frozen=await executeOperation(database,'freeze_storage_warning_units',request({now_at:START}));
  assert.equal(frozen.frozen,true);assert.equal(frozen.units[0].kind,'upload');assert.deepEqual(frozen.units.map((u)=>u.resource_id),[OLD_UPLOAD]);
  assert.equal(database.rows.storage_billing_warning_units.length,1);
  database.rows.upload_files.push({id:'later',file_size_bytes:500,created_at:START+1,files_metadata:{original:{s3_key:'later.enc'}}});
  const replay=await executeOperation(database,'freeze_storage_warning_units',request({now_at:START+WEEK}));
  assert.equal(replay.idempotent,true);assert.equal(replay.unit_selection_hash,frozen.unit_selection_hash);
  assert.deepEqual(replay.units,frozen.units);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection
test('safe-set shortage holds before selection or deletion',async()=>{
  const database=expiryDb();await freeze(database);
  database.raw=async(sql)=>sql.includes('WITH requested AS')?{rows:[{owner_kind:'personal',owner_id:USER,
    measurement_at:START,categories:{legacy_uploads:String(1073742000)},incomplete:false}]}:
    sql.includes('WITH requested_objects AS')?{rows:[{refs:[],ambiguous:false}]}:{rows:[]};
  const held=await executeOperation(database,'freeze_storage_warning_units',request({now_at:START}));
  assert.equal(held.reason,'no_complete_safe_set');assert.equal(held.held,true);
  assert.equal(database.rows.storage_billing_warning_units,undefined);
  assert.equal(database.rows.upload_files.length,2);assert.equal(database.rows.storage_billing_owner_state[0].warning_count,0);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection,billing.storage.expiry-invoice-closure
test('expiry removes selected references, queues regional purge and waives only warned invoices',async()=>{
  const database=expiryDb();const {frozen,period}=await deliveredExpiry(database);
  const later=await executeOperation(database,'freeze_storage_period',request({
    period_start_at:START+WEEK,measured_bytes:1073741825,credits_due:3,
    charge_id:`storage:${OWNER}:${START+WEEK}`,free_bytes:1073741824,credits_per_gib:3,
    policy_version:'storage-v2',source_version:'logical-s3-v1',category_bytes:{uploads:1073741825}}));
  assert.equal((await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id,
    {now_at:START+4*WEEK-1}))).applied,false);
  const applied=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(applied.applied,true);assert.equal(applied.after_bytes,64);assert.equal(applied.removed_bytes,1073741888);
  assert.deepEqual(database.rows.upload_files.map((u)=>u.id),[NEW_UPLOAD]);
  assert.equal(database.rows.storage_billing_periods.find((p)=>p.id===period.id).state,'waived_on_expiry');
  assert.equal(database.rows.storage_billing_periods.find((p)=>p.id===later.period.id).state,'unpaid');
  const tombstone=database.rows.storage_deletion_tombstones[0];assert.equal(tombstone.state,'pending');
  assert.deepEqual(JSON.parse(tombstone.purge_states),{'1':{nbg1:'pending',fsn1:'pending',hel1:'pending'}});
  const replay=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(replay.idempotent,true);assert.deepEqual(replay.removed_row_ids,applied.removed_row_ids);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.personal-expiry-selection,billing.storage.exact-settlement
test('late bounce, payment, changed balance and changed selection prevent any removal',async()=>{
  for(const fence of ['bounce','payment','balance','selection']) {
    const database=expiryDb();const {frozen,period}=await deliveredExpiry(database);
    if(fence==='bounce') database.rows.email_deliveries[0].provider_delivery_state='failed';
    if(fence==='payment') database.rows.billing_charge_identities=[{charge_id:period.charge_id,state:'committed'}];
    if(fence==='balance') database.rows.directus_users[0].encrypted_credit_balance='new-topup-balance';
    if(fence==='selection') database.rows.upload_files[0].fingerprint='changed-canonical-row';
    if(fence==='balance') await assert.rejects(executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id)),
      (error)=>error.code==='stale_credit_balance');
    else assert.equal((await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id))).applied,false);
    assert.equal(database.rows.upload_files.length,2);assert.equal(database.rows.storage_deletion_tombstones,undefined);
  }
});

// contract-test: supporting surface=rest_api assertions=billing.storage.logical-usage,billing.storage.personal-expiry-selection,billing.storage.expiry-invoice-closure
test('authoritative measurement failure rolls back row removal, invoice waiver and tombstones',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);const originalRaw=database.raw;
  database.raw=async(sql,bindings)=> {
    if(sql.includes('WITH requested AS')&&database.rows.upload_files.length===1) return {rows:[{owner_kind:'personal',owner_id:USER,
      measurement_at:START,categories:{legacy_uploads:String(1073741825)},incomplete:false}]};
    return originalRaw(sql,bindings);
  };
  await assert.rejects(executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id)),
    (error)=>error.code==='storage_expiry_after_quote_above_free');
  assert.equal(database.rows.upload_files.length,2);assert.equal(database.rows.storage_deletion_tombstones,undefined);
  assert.equal(database.rows.storage_billing_periods[0].state,'unpaid');
});

// contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry,billing.storage.personal-expiry-selection
test('selection receipt mismatch never starts the delivered warning clock',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);
  database.rows.storage_billing_owner_state[0].warning_count=0;
  database.rows.email_deliveries[0].metadata.context.unit_selection_hash='changed';
  await assert.rejects(executeOperation(database,'acknowledge_storage_warning',request({episode_id:frozen.episode_id,
    warning_stage:1,delivery_id:database.rows.email_deliveries[0].id,now_at:START})),
    (error)=>error.code==='storage_warning_selection_mismatch');
  assert.equal(database.rows.storage_billing_owner_state[0].warning_count,0);
});


// contract-test: supporting surface=rest_api assertions=billing.storage.weekly-quote,billing.storage.personal-expiry-selection
test('usage already under free allowance preserves notified objects and unpaid debt',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);
  database.rows.upload_files[0].file_size_bytes=100;
  const result=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(result.reason,'within_free_storage');assert.equal(result.applied,false);
  assert.equal(database.rows.upload_files.length,2);assert.equal(database.rows.storage_billing_periods[0].state,'unpaid');
});

// contract-test: supporting surface=rest_api assertions=billing.storage.expiry-invoice-closure
test('permanent invoice audit replays expiry after the owner starts another episode',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);
  const first=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  const owner=database.rows.storage_billing_owner_state[0];
  assert.equal(owner.warning_count,0);assert.equal(owner.episode_id,null);
  owner.episode_id='99999999-9999-4999-8999-999999999999';owner.expiry_audit=null;
  const replay=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(replay.idempotent,true);assert.deepEqual(replay.removed_row_ids,first.removed_row_ids);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection
test('expiry stops after the oldest notified unit when usage has fallen since freeze',async()=>{
  const database=expiryDb();const chunk=600*1024*1024;
  database.rows.upload_files[0].file_size_bytes=chunk;
  database.rows.upload_files[1].file_size_bytes=chunk;
  database.rows.upload_files.push({id:'99999999-9999-4999-8999-999999999999',user_id:USER,
    file_size_bytes:chunk,created_at:START+86400,files_metadata:{original:{s3_key:'latest.enc'}}});
  const {frozen}=await deliveredExpiry(database);assert.equal(frozen.units.length,2);
  database.rows.upload_files.pop();
  const applied=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(applied.applied,true);assert.equal(applied.removed_unit_ids.length,1);
  assert.deepEqual(database.rows.upload_files.map((unit)=>unit.id),[NEW_UPLOAD]);assert.equal(applied.after_bytes,chunk);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.personal-expiry-selection
test('later paid storage protects the frozen selection',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);
  database.rows.storage_billing_periods.push({id:'later-paid',hashed_user_id:OWNER,state:'paid',created_at:new Date((START+WEEK)*1000)});
  const held=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(held.reason,'later_paid_storage');assert.equal(database.rows.upload_files.length,2);
});


// contract-test: supporting surface=rest_api assertions=billing.storage.expiry-invoice-closure,billing.storage.exact-settlement
test('waived storage invoice rejects a stale new debit after top-up and cannot become paid',async()=>{
  const database=expiryDb();const {frozen,period}=await deliveredExpiry(database);
  await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  database.rows.directus_users[0].encrypted_credit_balance='new-topup-balance';
  const usageId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  await assert.rejects(executeOperation(database,'commit_personal_charge',request({
    charge_id:period.charge_id,app_id:'system',skill_id:'storage',requested_credits:3,charged_credits:3,
    expected_encrypted_balance:'new-topup-balance',new_encrypted_balance:'stale-debit-balance',
    usage_entry:{id:usageId,charge_id:period.charge_id,user_id_hash:OWNER,app_id:'system',skill_id:'storage',
      encrypted_credits_costs_total:'opaque-credits',created_at:START+4*WEEK,updated_at:START+4*WEEK}})),
    (error)=>error.code==='storage_period_not_chargeable');
  assert.equal(database.rows.directus_users[0].encrypted_credit_balance,'new-topup-balance');
  assert.equal(database.rows.billing_charge_identities,undefined);assert.equal(database.rows.usage,undefined);
  await assert.rejects(executeOperation(database,'mark_storage_period_paid',request({period_id:period.id})),
    (error)=>error.code==='storage_period_not_chargeable');
  assert.equal(database.rows.storage_billing_periods[0].state,'waived_on_expiry');
});

// contract-test: supporting surface=rest_api assertions=billing.storage.exact-settlement,billing.storage.personal-expiry-selection
test('unresolved storage settlements hold every removal',async()=>{
  const database=expiryDb();const {frozen,period}=await deliveredExpiry(database);
  database.rows.billing_settlement_outbox=[{charge_id:period.charge_id,hashed_user_id:OWNER,state:'retry_scheduled'}];
  const held=await executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id));
  assert.equal(held.reason,'storage_settlement_unresolved');assert.equal(database.rows.upload_files.length,2);
  assert.equal(database.rows.storage_deletion_tombstones,undefined);
});


// contract-test: supporting surface=rest_api assertions=billing.storage.personal-expiry-selection,billing.storage.logical-usage
test('ambiguous canonical recovery inventory blocks deletion and waiver',async()=>{
  const database=expiryDb();const {frozen}=await deliveredExpiry(database);const originalRaw=database.raw;
  database.raw=async(sql,bindings)=>sql.includes('WITH requested_objects AS')&&sql.includes(' AS ambiguous')
    ?{rows:[{refs:[],ambiguous:true}]}:originalRaw(sql,bindings);
  await assert.rejects(executeOperation(database,'apply_storage_expiry',expiryRequest(frozen.episode_id)),
    (error)=>error.code==='storage_reference_inventory_incomplete');
  assert.equal(database.rows.upload_files.length,2);assert.equal(database.rows.storage_billing_periods[0].state,'unpaid');
  assert.equal(database.rows.storage_deletion_tombstones,undefined);
});


// contract-test: supporting surface=rest_api assertions=billing.storage.legacy-cutover-safe,billing.storage.exact-settlement
test('exact legacy Unix-week storage key can drain while new missing invoice keys cannot debit',async()=>{
  const database=expiryDb();const legacyId=`storage:${OWNER}:${Math.floor(START/WEEK)}`;
  const usageId='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const payload=request({charge_id:legacyId,app_id:'system',skill_id:'storage',requested_credits:3,charged_credits:3,
    expected_encrypted_balance:'opaque-expiry-balance',new_encrypted_balance:'legacy-drained-balance',
    usage_entry:{id:usageId,charge_id:legacyId,user_id_hash:OWNER,app_id:'system',skill_id:'storage',
      encrypted_credits_costs_total:'opaque-credits',created_at:START,updated_at:START}});
  const committed=await executeOperation(database,'commit_personal_charge',payload,new Date(START*1000));
  assert.equal(committed.state,'committed');assert.equal(committed.idempotent,false);
  const replay=await executeOperation(database,'commit_personal_charge',payload,new Date(START*1000));
  assert.equal(replay.idempotent,true);assert.equal(database.rows.billing_charge_identities.length,1);
  const newId=`storage:${OWNER}:${START}`;
  await assert.rejects(executeOperation(database,'commit_personal_charge',{...payload,charge_id:newId,
    expected_encrypted_balance:'legacy-drained-balance',usage_entry:{...payload.usage_entry,charge_id:newId}},new Date(START*1000)),
    (error)=>error.code==='storage_period_not_chargeable');
  assert.equal(database.rows.directus_users[0].encrypted_credit_balance,'legacy-drained-balance');
});


// contract-test: supporting surface=rest_api assertions=billing.storage.expiry-invoice-closure,billing.storage.exact-settlement
test('waived storage debt cannot enqueue a delayed settlement after expiry', async () => {
  const database = expiryDb();
  const { frozen, period } = await deliveredExpiry(database);
  await executeOperation(database, 'apply_storage_expiry', expiryRequest(frozen.episode_id));
  await assert.rejects(executeOperation(database, 'create_or_reuse_pending_settlement', request({
    charge_id: period.charge_id, vault_key_id: 'test-vault-key',
    encrypted_settlement_payload: 'opaque-payload', settlement_payload_hash: 'a'.repeat(64),
    retryable_error_code: 'stale_balance',
  })), (error) => error.code === 'storage_period_not_chargeable');
  assert.equal(database.rows.billing_settlement_outbox, undefined);
  assert.equal(database.rows.storage_billing_periods[0].state, 'waived_on_expiry');
});
