import assert from 'node:assert/strict';
import test from 'node:test';
import { executeAuthoring, AuthoringError } from '../src/operations.js';

const OWNER = `user_sha256:${'a'.repeat(64)}`;
const HASH = `sha256:${'b'.repeat(64)}`;
const checksum = `sha256:${'c'.repeat(64)}`;
const ref = (name) => `vault://workflows/${name}/00000000-0000-4000-8000-000000000000`;

class Query {
  constructor(rows) { this.rows = rows; this.predicates = []; this.maximum = Infinity; }
  where(fields, operator, value) {
    if (typeof fields === 'string' && operator === '<=') {
      this.predicates.push((row) => row[fields] <= value);
    } else this.predicates.push((row) => Object.entries(fields).every(([key, item]) => row[key] === item));
    return this;
  }
  whereNotNull(key) { this.predicates.push((row) => row[key] !== null && row[key] !== undefined); return this; }
  whereIn(key, values) { this.predicates.push((row) => values.includes(row[key])); return this; }
  orderBy() { return this; }
  limit(maximum) { this.maximum = maximum; return this; }
  forUpdate() { return this; }
  selected() { return this.rows.filter((row) => this.predicates.every((predicate) => predicate(row))).slice(0, this.maximum); }
  first() { return Promise.resolve(this.selected()[0]); }
  select() { return Promise.resolve(this.selected()); }
  then(resolve, reject) { return Promise.resolve(this.selected()).then(resolve, reject); }
  insert(row) { this.rows.push(structuredClone(row)); return Promise.resolve(); }
  update(changes) { for (const row of this.selected()) Object.assign(row, structuredClone(changes)); return Promise.resolve(); }
  delete() { for (const row of this.selected()) this.rows.splice(this.rows.indexOf(row), 1); return Promise.resolve(); }
}

class FakeDatabase {
  constructor() {
    const database = (name) => new Query(database.tables[name]);
    database.tables = Object.fromEntries([
      'workflows', 'workflow_versions', 'workflow_triggers', 'workflow_runs', 'workflow_encrypted_blobs',
      'workflow_input_mutations', 'workflow_authoring_operations', 'workflow_website_state', 'workflow_chat_deliveries',
      'workflow_delivery_history',
    ].map((table) => [table, []]));
    database.transaction = (callback) => {
      const copy = structuredClone(database.tables);
      const trx = (name) => new Query(copy[name]);
      trx.raw = async () => undefined;
      return Promise.resolve(callback(trx)).then((result) => { database.tables = copy; return result; });
    };
    return database;
  }
}

function createBody(operationId, workflowId) {
  const titleRef = ref(`title-${workflowId}`);
  const graphRef = ref(`graph-${workflowId}`);
  const versionId = `version-${workflowId}`;
  const record = {
    id: workflowId, owner_hash: OWNER, version: 1, status: 'disabled', enabled: false,
    current_version_id: versionId, encrypted_title_ref: titleRef,
    encrypted_title_checksum: checksum, encrypted_graph_ref: graphRef,
    encrypted_graph_checksum: checksum, versions: [{ id: versionId, version_number: 1,
      encrypted_graph_ref: graphRef, encrypted_graph_checksum: checksum, created_at: 1 }],
    created_at: 1, updated_at: 1,
  };
  return {
    owner_hash: OWNER, operation_id: operationId, request_hash: HASH, session_id: null,
    writes: [{ workflow_id: workflowId, expected_version: null, record, trigger: null }],
    blobs: [titleRef, graphRef].map((blobRef) => ({ ref: blobRef, owner_hash: OWNER,
      kind: 'workflow_test', ciphertext: 'vault:v1:ciphertext', checksum,
      vault_key_ref: 'key', key_version: '1', created_at: 1 })),
    mutations: [{ id: '00000000-0000-4000-8000-000000000001', operation_id: operationId,
      session_id: null, hashed_user_id: OWNER, type: 'create_workflow', target_type: 'workflow',
      target_id: workflowId, encrypted_before_ref: null, encrypted_before_checksum: null,
      encrypted_after_ref: null, encrypted_after_checksum: null, undone_at: null, created_at: 1 }],
    outcomes: [{ workflow_id: workflowId, version: 1, after_ref: null }],
  };
}

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('one transaction publishes head, version, blobs, mutation and receipt once', async () => {
  const db = new FakeDatabase();
  const body = createBody('operation-1', '00000000-0000-4000-8000-000000000002');
  const first = await executeAuthoring(db, '/', body);
  const second = await executeAuthoring(db, '/', body);
  assert.deepEqual(second, first);
  assert.equal(db.tables.workflows.length, 1);
  assert.equal(db.tables.workflow_versions.length, 1);
  assert.equal(db.tables.workflow_encrypted_blobs.length, 2);
  assert.equal(db.tables.workflow_input_mutations.length, 1);
  assert.equal(db.tables.workflow_authoring_operations.length, 1);
});

// contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
test('team workflow creation persists the requested context and rejects a forged context', async () => {
  const db = new FakeDatabase();
  const body = createBody('team-create', '00000000-0000-4000-8000-000000000006');
  const teamHash = 'd'.repeat(64);
  body.hashed_team_id = teamHash;
  body.writes[0].record.hashed_team_id = teamHash;
  await executeAuthoring(db, '/', body);
  assert.equal(db.tables.workflows[0].hashed_team_id, teamHash);

  const memberEdit = createBody('team-member-edit', body.writes[0].workflow_id);
  memberEdit.hashed_team_id = teamHash;
  memberEdit.writes[0].expected_version = 1;
  memberEdit.writes[0].record.version = 2;
  memberEdit.writes[0].record.hashed_team_id = teamHash;
  memberEdit.outcomes[0].version = 2;
  await executeAuthoring(db, '/', memberEdit);
  assert.equal(db.tables.workflows[0].version, 2);

  const wrongTeam = createBody('wrong-team-edit', body.writes[0].workflow_id);
  wrongTeam.hashed_team_id = 'e'.repeat(64);
  wrongTeam.writes[0].expected_version = 2;
  wrongTeam.writes[0].record.version = 3;
  wrongTeam.writes[0].record.hashed_team_id = wrongTeam.hashed_team_id;
  wrongTeam.outcomes[0].version = 3;
  await assert.rejects(executeAuthoring(db, '/', wrongTeam), (error) =>
    error instanceof AuthoringError && error.code === 'head_conflict');

  const forged = createBody('team-forged', '00000000-0000-4000-8000-000000000007');
  forged.hashed_team_id = teamHash;
  await assert.rejects(executeAuthoring(db, '/', forged), (error) =>
    error instanceof AuthoringError && error.code === 'invalid_owner');
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('a conflicting target leaves an earlier target unchanged', async () => {
  const db = new FakeDatabase();
  const first = createBody('setup-1', '00000000-0000-4000-8000-000000000002');
  const second = createBody('setup-2', '00000000-0000-4000-8000-000000000003');
  await executeAuthoring(db, '/', first);
  await executeAuthoring(db, '/', second);
  const edit = createBody('edit', first.writes[0].workflow_id);
  edit.writes[0].expected_version = 1;
  edit.writes[0].record.version = 2;
  edit.writes[0].record.updated_at = 2;
  edit.outcomes[0].version = 2;
  const stale = createBody('edit', second.writes[0].workflow_id);
  stale.writes[0].expected_version = 2;
  stale.writes[0].record.version = 3;
  edit.writes.push(stale.writes[0]);
  edit.mutations.push({ ...stale.mutations[0], id: '00000000-0000-4000-8000-000000000004',
    operation_id: 'edit', type: 'update_workflow' });
  edit.outcomes.push({ ...stale.outcomes[0], version: 3 });
  const before = structuredClone(db.tables);
  await assert.rejects(executeAuthoring(db, '/', edit), (error) => error instanceof AuthoringError
    && error.status === 409 && error.code === 'head_conflict');
  assert.deepEqual(db.tables, before);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('receipt query does not disclose another owner operation', async () => {
  const db = new FakeDatabase();
  const body = createBody('operation-1', '00000000-0000-4000-8000-000000000002');
  await executeAuthoring(db, '/', body);
  await assert.rejects(executeAuthoring(db, '/receipt', { operation_id: body.operation_id,
    owner_hash: `user_sha256:${'d'.repeat(64)}`, request_hash: HASH }),
  (error) => error instanceof AuthoringError && error.status === 409);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('undo checks original postcommit versions and marks the original ledger atomically', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  await executeAuthoring(db, '/', createBody('create', workflowId));
  const undo = createBody('undo', workflowId);
  undo.undo_of_operation_id = 'create';
  undo.writes[0].expected_version = 1;
  undo.writes[0].record.version = 2;
  undo.writes[0].record.status = 'deleted';
  undo.blobs = [];
  undo.mutations[0].id = '00000000-0000-4000-8000-000000000005';
  undo.mutations[0].type = 'delete_workflow';
  undo.outcomes[0].version = 2;
  await executeAuthoring(db, '/', undo);
  assert.equal(db.tables.workflows[0].version, 2);
  assert.equal(db.tables.workflows[0].status, 'deleted');
  assert.ok(db.tables.workflow_input_mutations.find((row) => row.operation_id === 'create').undone_at);
  assert.equal(db.tables.workflow_authoring_operations.length, 2);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('legacy metadata writer uses the read version and preserves a newer graph', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  await executeAuthoring(db, '/', createBody('create', workflowId));
  const stale = structuredClone(JSON.parse(db.tables.workflows[0].record_json));
  const metadata = { owner_hash: OWNER, workflow_id: workflowId,
    expected_version: 1, record: { ...stale, lifecycle: 'persisted', kept_at: 2, updated_at: 2 } };
  const saved = await executeAuthoring(db, '/legacy-head', metadata);
  assert.equal(saved.record.version, 2);
  assert.equal(saved.record.encrypted_graph_ref, stale.encrypted_graph_ref);
  await assert.rejects(executeAuthoring(db, '/legacy-head', metadata),
    (error) => error instanceof AuthoringError && error.code === 'head_conflict');
  assert.equal(db.tables.workflows[0].version, 2);
  assert.equal(JSON.parse(db.tables.workflows[0].record_json).current_version_id, stale.current_version_id);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('temporary expiration deletes only the unchanged due workflow', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  const body = createBody('create', workflowId);
  body.writes[0].record.lifecycle = 'temporary';
  body.writes[0].record.auto_delete_at = 100;
  const snapshotRef = ref('temporary-mutation-snapshot');
  body.mutations[0].encrypted_after_ref = snapshotRef;
  body.mutations[0].encrypted_after_checksum = checksum;
  body.outcomes[0].after_ref = snapshotRef;
  body.blobs.push({ ...body.blobs[0], ref: snapshotRef, kind: 'workflow_mutation' });
  await executeAuthoring(db, '/', body);
  await assert.rejects(executeAuthoring(db, '/expire-temporary', {
    workflow_id: workflowId, owner_hash: OWNER, hashed_team_id: null,
    expected_version: 1, cutoff: 99,
  }), (error) => error instanceof AuthoringError && error.code === 'expiration_conflict');
  assert.equal(db.tables.workflows.length, 1);
  const result = await executeAuthoring(db, '/expire-temporary', {
    workflow_id: workflowId, owner_hash: OWNER, hashed_team_id: null,
    expected_version: 1, cutoff: 100,
  });
  assert.equal(result.expired, true);
  assert.equal(db.tables.workflows.length, 0);
  assert.equal(db.tables.workflow_encrypted_blobs.length, 0);
  assert.equal(db.tables.workflow_input_mutations.length, 0);
  assert.deepEqual(JSON.parse(db.tables.workflow_authoring_operations[0].outcomes_json), [
    { workflow_id: workflowId, version: 1, after_ref: null, expired: true },
  ]);
});

// contract-test: supporting surface=rest_api assertions=workflows.chat.embedded-lifecycle
test('chat-owned purge removes private history and keeps an independent saved copy', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  const copyId = '00000000-0000-4000-8000-000000000003';
  const body = createBody('chat-create', workflowId);
  body.writes[0].record.lifecycle = 'chat_embed';
  body.writes[0].record.source_chat_id = 'source-chat';
  body.writes[0].record.auto_delete_at = null;
  const snapshotRef = ref('chat-mutation-snapshot');
  body.mutations[0].encrypted_after_ref = snapshotRef;
  body.mutations[0].encrypted_after_checksum = checksum;
  body.outcomes[0].after_ref = snapshotRef;
  body.blobs.push({ ...body.blobs[0], ref: snapshotRef, kind: 'workflow_mutation' });
  await executeAuthoring(db, '/', body);
  await executeAuthoring(db, '/', createBody('saved-copy', copyId));
  const inputRef = ref('chat-input');
  const invocationRef = ref('chat-invocation');
  const outputRef = ref('chat-output');
  const deliveryKeyRef = ref('chat-delivery-identity-key');
  db.tables.workflows.find((row) => row.workflow_id === workflowId).encrypted_delivery_key_ref = deliveryKeyRef;
  for (const privateRef of [inputRef, invocationRef, outputRef, deliveryKeyRef]) {
    db.tables.workflow_encrypted_blobs.push({ ...body.blobs[0], ref: privateRef,
      hashed_user_id: OWNER });
  }
  db.tables.workflow_runs.push({ id: 'run-1', workflow_id: workflowId, hashed_user_id: OWNER,
    encrypted_input: inputRef, encrypted_invocation_ref: invocationRef,
    encrypted_output_summary: outputRef, record_json: '{}' });
  db.tables.workflow_chat_deliveries.push({ id: 'delivery-1', workflow_id: workflowId,
    hashed_user_id: OWNER.replace(/^user_sha256:/, ''), status: 'pending',
    encrypted_payload: 'private', claim_generation: 0, revision: 0 });
  db.tables.workflow_delivery_history.push({ id: 'history-1', workflow_id: workflowId,
    hashed_user_id: OWNER });
  const purge = { workflow_id: workflowId, owner_hash: OWNER, hashed_team_id: null,
    expected_version: 1, source_chat_id: 'source-chat', cutoff: 100 };
  await assert.rejects(executeAuthoring(db, '/purge-chat-embed', { ...purge,
    source_chat_id: 'different-chat' }), (error) => error instanceof AuthoringError
    && error.code === 'chat_purge_conflict');
  await assert.rejects(executeAuthoring(db, '/purge-chat-embed', { ...purge,
    owner_hash: `user_sha256:${'d'.repeat(64)}` }), (error) => error instanceof AuthoringError
    && error.code === 'head_conflict');
  assert.deepEqual(await executeAuthoring(db, '/purge-chat-embed', purge), { purged: true });
  assert.deepEqual(db.tables.workflows.map((row) => row.workflow_id), [copyId]);
  assert.equal(db.tables.workflow_runs.length, 0);
  assert.equal(db.tables.workflow_chat_deliveries.length, 0);
  assert.equal(db.tables.workflow_delivery_history.length, 0);
  assert.equal(db.tables.workflow_input_mutations.length, 1);
  assert.deepEqual(db.tables.workflow_encrypted_blobs.map((blob) => blob.ref).sort(),
    [ref(`title-${copyId}`), ref(`graph-${copyId}`)].sort());
  assert.deepEqual(JSON.parse(db.tables.workflow_authoring_operations[0].outcomes_json), [
    { workflow_id: workflowId, version: 1, after_ref: null, expired: true },
  ]);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('seven day cleanup removes snapshots but keeps a content-free idempotency receipt', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  const body = createBody('cleanup', workflowId);
  const snapshotRef = ref('private-undo-snapshot');
  body.mutations[0].encrypted_after_ref = snapshotRef;
  body.mutations[0].encrypted_after_checksum = checksum;
  body.outcomes[0].after_ref = snapshotRef;
  body.blobs.push({ ...body.blobs[0], ref: snapshotRef, kind: 'workflow_mutation', expires_at: 604801 });
  await executeAuthoring(db, '/', body);
  assert.deepEqual(await executeAuthoring(db, '/prune-mutations', { owner_hash: OWNER, cutoff: 0 }), { pruned: 0 });
  assert.equal(db.tables.workflow_input_mutations.length, 1);
  assert.deepEqual(await executeAuthoring(db, '/prune-mutations', { owner_hash: OWNER, cutoff: 1 }), { pruned: 1 });
  assert.equal(db.tables.workflow_input_mutations.length, 0);
  assert.equal(db.tables.workflow_encrypted_blobs.some((blob) => blob.ref === snapshotRef), false);
  assert.equal(db.tables.workflow_encrypted_blobs.length, 2);
  assert.deepEqual(JSON.parse(db.tables.workflow_authoring_operations[0].outcomes_json), [
    { workflow_id: workflowId, version: 1, after_ref: null, expired: true },
  ]);
  const replay = await executeAuthoring(db, '/receipt', {
    operation_id: body.operation_id, owner_hash: OWNER, request_hash: HASH,
  });
  assert.equal(replay.found, true);
  assert.equal(replay.outcomes[0].expired, true);
});

// contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
test('authoring preserves a live trigger claim and fences trigger replacement', async () => {
  const db = new FakeDatabase();
  const workflowId = '00000000-0000-4000-8000-000000000002';
  const setup = createBody('setup', workflowId);
  setup.writes[0].trigger = {
    trigger_id: '00000000-0000-4000-8000-000000000007', workflow_id: workflowId,
    version_id: setup.writes[0].record.current_version_id, owner_hash: OWNER,
    owner_user_id: 'alice', trigger_type: 'schedule', enabled: true,
    next_run_at: 100, claim_generation: 0, created_at: 1, updated_at: 1,
  };
  await executeAuthoring(db, '/', setup);
  Object.assign(db.tables.workflow_triggers[0], {
    claim_status: 'claimed', claim_token_hash: 'live-token', claim_generation: 5,
    claimed_at: 100, claim_expires_at: 200, next_run_at: 120,
  });
  const edit = createBody('metadata-edit', workflowId);
  edit.writes[0].expected_version = 1;
  edit.writes[0].record.version = 2;
  edit.writes[0].trigger = { ...setup.writes[0].trigger, claim_generation: 0, next_run_at: 100 };
  edit.blobs = [];
  edit.outcomes[0].version = 2;
  await executeAuthoring(db, '/', edit);
  assert.equal(db.tables.workflow_triggers[0].claim_generation, 5);
  assert.equal(db.tables.workflow_triggers[0].claim_token_hash, 'live-token');
  assert.equal(db.tables.workflow_triggers[0].next_run_at, 120);

  const graphEdit = createBody('graph-edit', workflowId);
  graphEdit.writes[0].expected_version = 2;
  graphEdit.writes[0].record.version = 3;
  graphEdit.writes[0].record.current_version_id = 'new-graph-version';
  graphEdit.writes[0].record.versions.push({ ...graphEdit.writes[0].record.versions[0],
    id: 'new-graph-version', version_number: 2 });
  graphEdit.writes[0].trigger = { ...setup.writes[0].trigger, version_id: 'new-graph-version' };
  graphEdit.blobs = [];
  graphEdit.outcomes[0].version = 3;
  await assert.rejects(executeAuthoring(db, '/', graphEdit),
    (error) => error instanceof AuthoringError && error.code === 'trigger_claim_conflict');
  assert.equal(db.tables.workflows[0].version, 2);
});
