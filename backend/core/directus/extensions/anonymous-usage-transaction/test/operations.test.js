/* Focused contract tests for the internal anonymous usage transaction boundary. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import test from 'node:test';
import { isAuthorized } from '../src/index.js';
import { AnonymousUsageError, executeOperation } from '../src/operations.js';

const NOW = new Date('2026-08-25T12:00:00.000Z');
const budget = (overrides = {}) => ({ id: 'budget', enabled: true, monthly_budget_credits: 60000, daily_hard_cap_percent: 5, weekly_cap_percent: 25, per_identity_daily_cap_credits: 400, daily_used_credits: 0, weekly_used_credits: 0, monthly_used_credits: 0, daily_window_date: '2026-08-25', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08', updated_at: NOW, ...overrides });

function fakeDatabase(seed) {
  const rows = structuredClone(seed);
  const client = (table) => {
    const predicates = []; let ordering;
    const matching = () => (rows[table] ?? []).filter((row) => predicates.every((predicate) => predicate(row))).sort((a, b) => ordering ? (a[ordering.key] < b[ordering.key] ? (ordering.direction === 'desc' ? 1 : -1) : (a[ordering.key] > b[ordering.key] ? (ordering.direction === 'desc' ? -1 : 1) : 0)) : 0);
    const query = { where(values) { predicates.push((row) => Object.entries(values).every(([key, value]) => row[key] === value)); return query; }, andWhere(key, operator, value) { predicates.push((row) => operator === '<=' ? row[key] != null && new Date(row[key]) <= new Date(value) : row[key] === value); return query; }, orderBy(key, direction) { ordering = { key, direction }; return query; }, forUpdate() { return query; }, async first() { return matching()[0]; }, async insert(value) { rows[table] ??= []; if (rows[table].some((row) => row.request_id && row.request_id === value.request_id)) throw new Error('unique'); rows[table].push(structuredClone(value)); return 1; }, async update(values) { const found = matching(); found.forEach((row) => Object.assign(row, structuredClone(values))); return found.length; }, async del() { const found = new Set(matching()); rows[table] = (rows[table] ?? []).filter((row) => !found.has(row)); return found.size; }, then(resolve, reject) { return Promise.resolve(matching()).then(resolve, reject); } };
    return query;
  };
  client.rows = rows; client.raw = async () => ({ ok: true }); client.transaction = async (callback) => callback(client); return client;
}
const payload = (data) => ({ protocol_version: 1, ...data });
async function open(database, requestId = 'request') { return executeOperation(database, 'open_request', payload({ request_id: requestId, local_id_hash: 'local', ip_hash: 'ip' }), NOW); }

test('authentication fails closed', () => {
  assert.equal(isAuthorized({}, 'secret'), false); assert.equal(isAuthorized({ 'x-internal-service-token': 'wrong' }, 'secret'), false); assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, 'secret'), true);
});

test('hard caps reject reservation before any accounting write', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget({ daily_used_credits: 2990 })], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  await assert.rejects(executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'op', charge_id: 'charge', quoted_credits: 20 }), NOW), (error) => error instanceof AnonymousUsageError && error.code === 'budget_exhausted');
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 2990);
});

test('reservation atomically accounts budget and both daily identities', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  const result = await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'op', charge_id: 'charge', quoted_credits: 30 }), NOW);
  assert.equal(result.status, 'reserved'); assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 30); assert.deepEqual(database.rows.anonymous_free_usage_identity_daily.map((row) => row.used_credits).sort(), [30, 30]); assert.deepEqual(database.rows.anonymous_free_usage_reservations.find((row) => row.request_id === 'op').expires_at, new Date('2026-08-25T14:00:00.000Z'));
});

test('reservation idempotency verifies immutable operation identity', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  const data = payload({ parent_request_id: 'request', operation_id: 'op', charge_id: 'charge', quoted_credits: 30 }); await executeOperation(database, 'reserve_operation', data, NOW);
  assert.equal((await executeOperation(database, 'reserve_operation', data, NOW)).idempotent, true);
  await assert.rejects(executeOperation(database, 'reserve_operation', { ...data, quoted_credits: 31 }, NOW), (error) => error.code === 'operation_identity_mismatch');
});

test('finalization rejects actual credits above quote', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database); await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'op', charge_id: 'charge', quoted_credits: 30 }), NOW);
  await assert.rejects(executeOperation(database, 'finalize_charge', payload({ charge_id: 'charge', actual_credits: 31 }), NOW), (error) => error.code === 'actual_exceeds_quote');
});

test('finalization rejects a charge spanning different pseudonymous identities', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_identity_daily: [], anonymous_free_usage_reservations: [
    { id: 'one', request_id: 'one', charge_id: 'charge', local_id_hash: 'local-a', ip_hash: 'ip-a', reserved_credits: 10, finalized_credits: 0, status: 'reserved' },
    { id: 'two', request_id: 'two', charge_id: 'charge', local_id_hash: 'local-b', ip_hash: 'ip-b', reserved_credits: 10, finalized_credits: 0, status: 'reserved' },
  ] });
  await assert.rejects(executeOperation(database, 'finalize_charge', payload({ charge_id: 'charge', actual_credits: 10 }), NOW), (error) => error.code === 'charge_identity_mismatch');
});

test('finalize and release refund only counters in matching windows', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget({ daily_used_credits: 30, weekly_used_credits: 30, monthly_used_credits: 30 })], anonymous_free_usage_identity_daily: [{ id: 'local', identity_hash: 'local', window_date: '2026-08-25', used_credits: 30 }, { id: 'ip', identity_hash: 'ip', window_date: '2026-08-25', used_credits: 30 }], anonymous_free_usage_reservations: [{ id: 'op', request_id: 'op', charge_id: 'charge', local_id_hash: 'local', ip_hash: 'ip', reserved_credits: 30, finalized_credits: 0, status: 'reserved', daily_window_date: 'old', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08' }] });
  await executeOperation(database, 'finalize_charge', payload({ charge_id: 'charge', actual_credits: 10 }), NOW);
  assert.deepEqual([database.rows.anonymous_free_usage_budget[0].daily_used_credits, database.rows.anonymous_free_usage_budget[0].weekly_used_credits, database.rows.anonymous_free_usage_budget[0].monthly_used_credits], [30, 10, 10]);
  database.rows.anonymous_free_usage_reservations.push({ id: 'release', request_id: 'release', reserved_credits: 10, finalized_credits: 0, status: 'reserved', local_id_hash: 'local', ip_hash: 'ip', daily_window_date: 'old', weekly_window_start: 'old', monthly_window_month: 'old' }); await executeOperation(database, 'release_operation', payload({ operation_id: 'release', reason: 'cancelled' }), NOW);
  assert.equal(database.rows.anonymous_free_usage_budget[0].weekly_used_credits, 10);
});

test('expired billable reservations release matching capacity exactly once and retain the attempt', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget({ daily_used_credits: 30, weekly_used_credits: 30, monthly_used_credits: 30 })], anonymous_free_usage_identity_daily: [{ id: 'local', identity_hash: 'local', window_date: '2026-08-25', used_credits: 30 }, { id: 'ip', identity_hash: 'ip', window_date: '2026-08-25', used_credits: 30 }], anonymous_free_usage_reservations: [{ id: 'billable', request_id: 'billable', status: 'reserved', expires_at: new Date('2026-08-25T10:00:00Z'), reserved_credits: 30, finalized_credits: 0, local_id_hash: 'local', ip_hash: 'ip', daily_window_date: '2026-08-25', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08' }] });
  await executeOperation(database, 'get_status', payload({}), NOW);
  assert.deepEqual([database.rows.anonymous_free_usage_budget[0].daily_used_credits, database.rows.anonymous_free_usage_budget[0].weekly_used_credits, database.rows.anonymous_free_usage_budget[0].monthly_used_credits], [0, 0, 0]);
  assert.deepEqual(database.rows.anonymous_free_usage_identity_daily.map((row) => row.used_credits), [0, 0]);
  assert.equal(database.rows.anonymous_free_usage_reservations[0].status, 'expired');
  assert.equal(database.rows.anonymous_free_usage_reservations[0].release_reason, 'timeout');
  await executeOperation(database, 'get_status', payload({}), NOW);
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 0);
});

test('expired zero-cost ledgers are deleted only after reserved children settle', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_identity_daily: [], anonymous_free_usage_reservations: [
    { id: 'parent', request_id: 'parent', status: 'request_open', expires_at: new Date('2026-08-25T00:00:00Z'), reserved_credits: 0 },
    { id: 'child', request_id: 'child', parent_request_id: 'parent', charge_id: 'child', status: 'reserved', expires_at: null, reserved_credits: 10 },
  ] });
  await executeOperation(database, 'get_status', payload({}), NOW);
  assert.ok(database.rows.anonymous_free_usage_reservations.some((row) => row.id === 'parent'));
  database.rows.anonymous_free_usage_reservations[1].status = 'finalized';
  await executeOperation(database, 'get_status', payload({}), NOW);
  assert.equal(database.rows.anonymous_free_usage_reservations.some((row) => row.id === 'parent'), false);
});

test('mixed finalized and reserved charge settlement allocates only remaining actual credits', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget({ daily_used_credits: 30, weekly_used_credits: 30, monthly_used_credits: 30 })], anonymous_free_usage_identity_daily: [{ id: 'local', identity_hash: 'local', window_date: '2026-08-25', used_credits: 30 }, { id: 'ip', identity_hash: 'ip', window_date: '2026-08-25', used_credits: 30 }], anonymous_free_usage_reservations: [
    { id: 'one', request_id: 'one', charge_id: 'charge', local_id_hash: 'local', ip_hash: 'ip', reserved_credits: 10, finalized_credits: 10, status: 'finalized', daily_window_date: '2026-08-25', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08' },
    { id: 'two', request_id: 'two', charge_id: 'charge', local_id_hash: 'local', ip_hash: 'ip', reserved_credits: 20, finalized_credits: 0, status: 'reserved', daily_window_date: '2026-08-25', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08' },
  ] });
  await executeOperation(database, 'finalize_charge', payload({ charge_id: 'charge', actual_credits: 15 }), NOW);
  assert.equal(database.rows.anonymous_free_usage_reservations[0].finalized_credits, 10);
  assert.equal(database.rows.anonymous_free_usage_reservations[1].finalized_credits, 5);
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 15);
});

test('checkpoint reclaims capacity for the next reservation without weakening hard caps', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'ai-1', charge_id: 'ai-main', quoted_credits: 400 }), NOW);
  const checkpoint = await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'ai-1', checkpoint_credits: 20 }), NOW);
  assert.deepEqual([checkpoint.reserved_credits, checkpoint.checkpoint_credits, checkpoint.effective_hold_credits], [400, 20, 20]);
  assert.equal((await executeOperation(database, 'get_request_budget', payload({ parent_request_id: 'request' }), NOW)).available_credits, 380);
  await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'ai-2', charge_id: 'ai-main', quoted_credits: 380 }), NOW);
  await assert.rejects(executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'extra', charge_id: 'extra', quoted_credits: 1 }), NOW), (error) => error.code === 'identity_budget_exhausted');
  assert.equal((await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'ai-1', checkpoint_credits: 20 }), NOW)).idempotent, true);
  await assert.rejects(executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'ai-1', checkpoint_credits: 21 }), NOW), (error) => error.code === 'operation_checkpoint_mismatch');
  assert.equal(database.rows.anonymous_free_usage_reservations.find((row) => row.request_id === 'ai-2').checkpoint_credits, null);
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 400);
  await assert.rejects(executeOperation(database, 'get_request_budget', payload({ parent_request_id: 'missing' }), NOW), (error) => error.code === 'request_closed');
});

test('zero and partial checkpoints remain reversible until idempotent terminal settlement', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'one', charge_id: 'shared', quoted_credits: 100 }), NOW);
  await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'one', checkpoint_credits: 0 }), NOW);
  await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'two', charge_id: 'shared', quoted_credits: 100 }), NOW);
  await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'two', checkpoint_credits: 5 }), NOW);
  await assert.rejects(executeOperation(database, 'finalize_charge', payload({ charge_id: 'shared', actual_credits: 6 }), NOW), (error) => error.code === 'actual_exceeds_hold');
  const finalized = await executeOperation(database, 'finalize_charge', payload({ charge_id: 'shared', actual_credits: 5 }), NOW);
  assert.equal(finalized.idempotent, false);
  assert.deepEqual(database.rows.anonymous_free_usage_reservations.filter((row) => row.charge_id === 'shared').map((row) => row.finalized_credits), [0, 5]);
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 5);
  assert.equal((await executeOperation(database, 'finalize_charge', payload({ charge_id: 'shared', actual_credits: 5 }), NOW)).idempotent, true);
});

test('checkpointed holds release or expire once and refunds stay within their original windows', async () => {
  const database = fakeDatabase({ anonymous_free_usage_budget: [budget()], anonymous_free_usage_reservations: [], anonymous_free_usage_identity_daily: [] }); await open(database);
  await executeOperation(database, 'reserve_operation', payload({ parent_request_id: 'request', operation_id: 'waived', charge_id: 'waived', quoted_credits: 30 }), NOW);
  await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'waived', checkpoint_credits: 10 }), NOW);
  await executeOperation(database, 'release_operation', payload({ operation_id: 'waived', reason: 'terminal_server_error' }), NOW);
  assert.equal(database.rows.anonymous_free_usage_budget[0].daily_used_credits, 0);
  assert.equal((await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'waived', checkpoint_credits: 10 }), NOW)).idempotent, true);
  await assert.rejects(executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'waived', checkpoint_credits: 9 }), NOW), (error) => error.code === 'operation_checkpoint_mismatch');

  const budgetRow = database.rows.anonymous_free_usage_budget[0];
  Object.assign(budgetRow, { daily_used_credits: 30, weekly_used_credits: 30, monthly_used_credits: 30 });
  database.rows.anonymous_free_usage_identity_daily.forEach((row) => { row.used_credits = 30; });
  database.rows.anonymous_free_usage_reservations.push({ id: 'old-window', request_id: 'old-window', charge_id: 'old-window', local_id_hash: 'local', ip_hash: 'ip', reserved_credits: 30, checkpoint_credits: null, finalized_credits: 0, status: 'reserved', daily_window_date: '2026-08-24', weekly_window_start: '2026-08-24', monthly_window_month: '2026-08', expires_at: new Date('2026-08-25T14:00:00Z') });
  await executeOperation(database, 'checkpoint_operation', payload({ operation_id: 'old-window', checkpoint_credits: 10 }), NOW);
  assert.deepEqual([budgetRow.daily_used_credits, budgetRow.weekly_used_credits, budgetRow.monthly_used_credits], [30, 10, 10]);
  assert.deepEqual(database.rows.anonymous_free_usage_identity_daily.map((row) => row.used_credits), [30, 30]);
  database.rows.anonymous_free_usage_reservations.find((row) => row.request_id === 'old-window').expires_at = new Date('2026-08-25T10:00:00Z');
  await executeOperation(database, 'get_status', payload({}), NOW);
  assert.deepEqual([budgetRow.daily_used_credits, budgetRow.weekly_used_credits, budgetRow.monthly_used_credits], [30, 0, 0]);
  assert.equal(database.rows.anonymous_free_usage_reservations.find((row) => row.request_id === 'old-window').status, 'expired');
});
