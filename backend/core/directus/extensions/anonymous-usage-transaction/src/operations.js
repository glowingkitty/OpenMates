/*
 * PostgreSQL/Knex transaction operations for anonymous shared free usage.
 * Locks always proceed budget, reservation, then lexically sorted identities.
 * The endpoint handles HMACs only; raw anonymous IDs, IPs, and content never enter it.
 */
import { randomUUID } from 'node:crypto';

const BUDGET = 'anonymous_free_usage_budget';
const IDENTITIES = 'anonymous_free_usage_identity_daily';
const RESERVATIONS = 'anonymous_free_usage_reservations';
const PROTOCOL_VERSION = 1;
const REQUEST_TTL_MS = 120 * 60_000;
const MAX_MONTHLY = 60_000;
const MAX_WEEKLY = 15_000;
const MAX_DAILY = 3_000;
const MAX_IDENTITY_DAILY = 400;
const MAX_INT = 2_147_483_647;

const FIELDS = Object.freeze({
  health_check: new Set(['protocol_version']),
  get_status: new Set(['protocol_version']),
  save_budget: new Set(['protocol_version', 'enabled', 'monthly_budget_credits', 'daily_hard_cap_percent', 'weekly_cap_percent', 'per_identity_daily_cap_credits', 'updated_by_admin_user_id']),
  open_request: new Set(['protocol_version', 'request_id', 'local_id_hash', 'ip_hash']),
  reserve_operation: new Set(['protocol_version', 'parent_request_id', 'operation_id', 'charge_id', 'quoted_credits']),
  finalize_charge: new Set(['protocol_version', 'charge_id', 'actual_credits']),
  release_operation: new Set(['protocol_version', 'operation_id', 'reason']),
  close_request: new Set(['protocol_version', 'request_id']),
});

export class AnonymousUsageError extends Error {
  constructor(status, code) { super(code); this.name = 'AnonymousUsageError'; this.status = status; this.code = code; }
}
const fail = (status, code) => { throw new AnonymousUsageError(status, code); };
const validObject = (value) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(400, 'invalid_request');
  return value;
};
const text = (value, code, max = 255) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
};
const integer = (value, code) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_INT) fail(400, code);
  return value;
};
const boolean = (value, code) => {
  if (typeof value !== 'boolean') fail(400, code);
  return value;
};
const count = (value) => Number.isSafeInteger(value) && value > 0 ? value : 0;
const request = (raw, operation) => {
  const body = validObject(raw); const allowed = FIELDS[operation];
  if (!allowed || Object.keys(body).some((key) => !allowed.has(key))) fail(400, 'invalid_request');
  if (body.protocol_version !== PROTOCOL_VERSION) fail(426, 'client_update_required');
  return body;
};
const dayKeys = (now) => {
  const date = new Date(now); const day = date.toISOString().slice(0, 10);
  const monday = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - ((date.getUTCDay() + 6) % 7)));
  return { day, week: monday.toISOString().slice(0, 10), month: day.slice(0, 7) };
};
const budgetResponse = (row) => ({
  id: row.id,
  enabled: Boolean(row.enabled), monthly_budget_credits: count(row.monthly_budget_credits),
  daily_hard_cap_percent: count(row.daily_hard_cap_percent), weekly_cap_percent: count(row.weekly_cap_percent),
  per_identity_daily_cap_credits: Math.min(count(row.per_identity_daily_cap_credits), MAX_IDENTITY_DAILY),
  daily_used_credits: count(row.daily_used_credits), weekly_used_credits: count(row.weekly_used_credits),
  monthly_used_credits: count(row.monthly_used_credits), daily_window_date: row.daily_window_date,
  weekly_window_start: row.weekly_window_start, monthly_window_month: row.monthly_window_month,
  updated_by_admin_user_id: row.updated_by_admin_user_id ?? null, updated_at: row.updated_at,
});
const reservationResponse = (row, idempotent) => ({
  request_id: row.request_id, charge_id: row.charge_id, reserved_credits: count(row.reserved_credits),
  finalized_credits: count(row.finalized_credits), status: row.status, idempotent,
});
const caps = (row) => {
  const monthly = Math.min(count(row.monthly_budget_credits), MAX_MONTHLY);
  return {
    monthly, daily: Math.min(Math.floor(monthly * Math.min(count(row.daily_hard_cap_percent), 100) / 100), MAX_DAILY),
    weekly: Math.min(Math.floor(monthly * Math.min(count(row.weekly_cap_percent), 100) / 100), MAX_WEEKLY),
    identity: Math.min(count(row.per_identity_daily_cap_credits), MAX_IDENTITY_DAILY),
  };
};

async function lockedBudget(trx, now) {
  const row = await trx(BUDGET).orderBy('updated_at', 'desc').forUpdate().first();
  if (!row) fail(409, 'budget_not_configured');
  const keys = dayKeys(now); const update = {};
  if (row.daily_window_date !== keys.day) Object.assign(update, { daily_window_date: keys.day, daily_used_credits: 0 });
  if (row.weekly_window_start !== keys.week) Object.assign(update, { weekly_window_start: keys.week, weekly_used_credits: 0 });
  if (row.monthly_window_month !== keys.month) Object.assign(update, { monthly_window_month: keys.month, monthly_used_credits: 0 });
  if (Object.keys(update).length) {
    update.updated_at = now;
    await trx(BUDGET).where({ id: row.id }).update(update);
    Object.assign(row, update);
  }
  return row;
}

async function expireReservations(trx, budget, now) {
  const reservations = await trx(RESERVATIONS).where({ status: 'reserved' }).andWhere('expires_at', '<=', now).forUpdate();
  for (const row of reservations) {
    const amount = count(row.reserved_credits); const refund = currentRefund(row, budget, amount);
    await trx(BUDGET).where({ id: budget.id }).update({
      daily_used_credits: Math.max(0, count(budget.daily_used_credits) - refund.daily),
      weekly_used_credits: Math.max(0, count(budget.weekly_used_credits) - refund.weekly),
      monthly_used_credits: Math.max(0, count(budget.monthly_used_credits) - refund.monthly),
      updated_at: now,
    });
    budget.daily_used_credits = Math.max(0, count(budget.daily_used_credits) - refund.daily);
    budget.weekly_used_credits = Math.max(0, count(budget.weekly_used_credits) - refund.weekly);
    budget.monthly_used_credits = Math.max(0, count(budget.monthly_used_credits) - refund.monthly);
    if (row.daily_window_date === budget.daily_window_date) {
      const identities = await lockedIdentities(trx, [row.local_id_hash, row.ip_hash], budget.daily_window_date);
      for (const identity of identities.values()) {
        const usedCredits = Math.max(0, count(identity.used_credits) - amount);
        await trx(IDENTITIES).where({ id: identity.id }).update({ used_credits: usedCredits, updated_at: now });
        identity.used_credits = usedCredits;
      }
    }
    await trx(RESERVATIONS).where({ id: row.id, status: 'reserved' }).update({ status: 'expired', release_reason: 'timeout', updated_at: now });
  }
  const expired = await trx(RESERVATIONS).where({ status: 'request_open' }).andWhere('expires_at', '<=', now).forUpdate();
  for (const row of expired) {
    const child = await trx(RESERVATIONS).where({ parent_request_id: row.request_id, status: 'reserved' }).first();
    if (!child) await trx(RESERVATIONS).where({ id: row.id, status: 'request_open' }).del();
  }
}

async function lockedIdentities(trx, hashes, day) {
  const unique = [...new Set(hashes)].sort();
  const result = new Map();
  for (const identityHash of unique) {
    let row = await trx(IDENTITIES).where({ identity_hash: identityHash, window_date: day }).forUpdate().first();
    if (!row) {
      row = { id: randomUUID(), identity_hash: identityHash, window_date: day, used_credits: 0 };
      try { await trx(IDENTITIES).insert(row); } catch (error) {
        row = await trx(IDENTITIES).where({ identity_hash: identityHash, window_date: day }).forUpdate().first();
        if (!row) throw error;
      }
    }
    result.set(identityHash, row);
  }
  return result;
}

async function status(database, raw, now) {
  request(raw, 'get_status');
  return database.transaction(async (trx) => {
    const configured = await trx(BUDGET).orderBy('updated_at', 'desc').forUpdate().first();
    if (!configured) return budgetResponse({});
    const row = await lockedBudget(trx, now); await expireReservations(trx, row, now); return budgetResponse(row);
  });
}

async function saveBudget(database, raw, now) {
  const body = request(raw, 'save_budget');
  const enabled = boolean(body.enabled, 'invalid_enabled');
  const monthly = integer(body.monthly_budget_credits, 'invalid_monthly_budget');
  const dailyPercent = integer(body.daily_hard_cap_percent, 'invalid_daily_percent');
  const weeklyPercent = integer(body.weekly_cap_percent, 'invalid_weekly_percent');
  const identityCap = integer(body.per_identity_daily_cap_credits, 'invalid_identity_cap');
  if (monthly > MAX_MONTHLY || dailyPercent > 100 || weeklyPercent > 100 || identityCap > MAX_IDENTITY_DAILY || (enabled && identityCap < 1)) fail(400, 'budget_limit_invalid');
  return database.transaction(async (trx) => {
    let row = await trx(BUDGET).orderBy('updated_at', 'desc').forUpdate().first();
    const keys = dayKeys(now);
    if (!row) {
      row = { id: randomUUID(), daily_used_credits: 0, weekly_used_credits: 0, monthly_used_credits: 0, daily_window_date: keys.day, weekly_window_start: keys.week, monthly_window_month: keys.month, created_at: now };
      await trx(BUDGET).insert(row);
    } else {
      row = await lockedBudget(trx, now);
    }
    const update = { enabled, monthly_budget_credits: monthly, daily_hard_cap_percent: dailyPercent, weekly_cap_percent: weeklyPercent, per_identity_daily_cap_credits: identityCap, updated_by_admin_user_id: body.updated_by_admin_user_id == null ? null : text(body.updated_by_admin_user_id, 'invalid_admin_id', 128), updated_at: now };
    await trx(BUDGET).where({ id: row.id }).update(update); return budgetResponse({ ...row, ...update });
  });
}

async function openRequest(database, raw, now) {
  const body = request(raw, 'open_request'); const requestId = text(body.request_id, 'invalid_request_id');
  const local = text(body.local_id_hash, 'invalid_identity_hash', 128); const ip = text(body.ip_hash, 'invalid_identity_hash', 128);
  return database.transaction(async (trx) => {
    const budget = await lockedBudget(trx, now); await expireReservations(trx, budget, now);
    const existing = await trx(RESERVATIONS).where({ request_id: requestId }).forUpdate().first();
    if (existing) return reservationResponse(existing, true);
    const limit = caps(budget);
    if (!budget.enabled) fail(409, 'budget_inactive');
    if (!limit.monthly || !limit.daily || !limit.weekly || !limit.identity || count(budget.monthly_used_credits) >= limit.monthly || count(budget.daily_used_credits) >= limit.daily || count(budget.weekly_used_credits) >= limit.weekly) fail(409, 'budget_exhausted');
    const row = { id: randomUUID(), request_id: requestId, parent_request_id: null, charge_id: null, local_id_hash: local, ip_hash: ip, reserved_credits: 0, finalized_credits: 0, status: 'request_open', created_at: now, updated_at: now, expires_at: new Date(now.getTime() + REQUEST_TTL_MS) };
    try { await trx(RESERVATIONS).insert(row); } catch (error) {
      const raced = await trx(RESERVATIONS).where({ request_id: requestId }).forUpdate().first(); if (!raced) throw error; return reservationResponse(raced, true);
    }
    return reservationResponse(row, false);
  });
}

async function reserveOperation(database, raw, now) {
  const body = request(raw, 'reserve_operation'); const parentId = text(body.parent_request_id, 'invalid_parent_request_id');
  const operationId = text(body.operation_id, 'invalid_operation_id'); const chargeId = text(body.charge_id, 'invalid_charge_id'); const quoted = integer(body.quoted_credits, 'invalid_quoted_credits');
  if (!quoted) fail(400, 'invalid_quoted_credits');
  return database.transaction(async (trx) => {
    const budget = await lockedBudget(trx, now); await expireReservations(trx, budget, now);
    const existing = await trx(RESERVATIONS).where({ request_id: operationId }).forUpdate().first();
    if (existing) {
      if (existing.parent_request_id !== parentId || existing.charge_id !== chargeId || count(existing.reserved_credits) !== quoted) fail(409, 'operation_identity_mismatch');
      return reservationResponse(existing, true);
    }
    const parent = await trx(RESERVATIONS).where({ request_id: parentId }).forUpdate().first();
    if (!parent || parent.status !== 'request_open') fail(409, 'request_closed');
    const limit = caps(budget); const identities = await lockedIdentities(trx, [parent.local_id_hash, parent.ip_hash], budget.daily_window_date);
    if (!budget.enabled) fail(409, 'budget_inactive');
    if (count(budget.daily_used_credits) + quoted > limit.daily || count(budget.weekly_used_credits) + quoted > limit.weekly || count(budget.monthly_used_credits) + quoted > limit.monthly) fail(409, 'budget_exhausted');
    if ([...identities.values()].some((row) => count(row.used_credits) + quoted > limit.identity)) fail(409, 'identity_budget_exhausted');
    const budgetUpdate = { daily_used_credits: count(budget.daily_used_credits) + quoted, weekly_used_credits: count(budget.weekly_used_credits) + quoted, monthly_used_credits: count(budget.monthly_used_credits) + quoted, updated_at: now };
    await trx(BUDGET).where({ id: budget.id }).update(budgetUpdate);
    for (const row of identities.values()) await trx(IDENTITIES).where({ id: row.id }).update({ used_credits: count(row.used_credits) + quoted, updated_at: now });
    const row = { id: randomUUID(), request_id: operationId, parent_request_id: parentId, charge_id: chargeId, local_id_hash: parent.local_id_hash, ip_hash: parent.ip_hash, reserved_credits: quoted, finalized_credits: 0, status: 'reserved', daily_window_date: budget.daily_window_date, weekly_window_start: budget.weekly_window_start, monthly_window_month: budget.monthly_window_month, created_at: now, updated_at: now, expires_at: new Date(now.getTime() + REQUEST_TTL_MS) };
    await trx(RESERVATIONS).insert(row);
    await trx(RESERVATIONS).where({ id: parent.id }).update({ expires_at: new Date(now.getTime() + REQUEST_TTL_MS), updated_at: now });
    return reservationResponse(row, false);
  });
}

function currentRefund(row, budget, amount) {
  return {
    daily: row.daily_window_date === budget.daily_window_date ? amount : 0,
    weekly: row.weekly_window_start === budget.weekly_window_start ? amount : 0,
    monthly: row.monthly_window_month === budget.monthly_window_month ? amount : 0,
  };
}
async function finalizeCharge(database, raw, now) {
  const body = request(raw, 'finalize_charge'); const chargeId = text(body.charge_id, 'invalid_charge_id'); const actual = integer(body.actual_credits, 'invalid_actual_credits');
  return database.transaction(async (trx) => {
    const budget = await lockedBudget(trx, now); const rows = await trx(RESERVATIONS).where({ charge_id: chargeId }).orderBy('request_id', 'asc').forUpdate();
    if (!rows.length) fail(404, 'reservation_not_found');
    const [first] = rows;
    if (rows.some((row) => row.local_id_hash !== first.local_id_hash || row.ip_hash !== first.ip_hash)) {
      fail(409, 'charge_identity_mismatch');
    }
    const totalQuote = rows.reduce((sum, row) => sum + count(row.reserved_credits), 0); const totalFinal = rows.filter((row) => row.status === 'finalized').reduce((sum, row) => sum + count(row.finalized_credits), 0);
    if (actual > totalQuote) fail(409, 'actual_exceeds_quote');
    if (!rows.some((row) => row.status === 'reserved')) {
      if (actual !== totalFinal) fail(409, 'charge_identity_mismatch'); return { charge_id: chargeId, actual_credits: actual, idempotent: true };
    }
    if (rows.some((row) => !['reserved', 'finalized'].includes(row.status))) fail(409, 'charge_identity_mismatch');
    if (actual < totalFinal) fail(409, 'charge_identity_mismatch');
    let remaining = actual - totalFinal; let refund = { daily: 0, weekly: 0, monthly: 0 }; let identityRefund = 0;
    for (const row of rows) {
      if (row.status === 'finalized') continue;
      const finalized = Math.min(count(row.reserved_credits), remaining); remaining -= finalized;
      const unused = count(row.reserved_credits) - finalized; const delta = currentRefund(row, budget, unused);
      refund = { daily: refund.daily + delta.daily, weekly: refund.weekly + delta.weekly, monthly: refund.monthly + delta.monthly };
      if (row.daily_window_date === budget.daily_window_date) identityRefund += unused;
      await trx(RESERVATIONS).where({ id: row.id }).update({ status: 'finalized', finalized_credits: finalized, updated_at: now });
    }
    await trx(BUDGET).where({ id: budget.id }).update({ daily_used_credits: Math.max(0, count(budget.daily_used_credits) - refund.daily), weekly_used_credits: Math.max(0, count(budget.weekly_used_credits) - refund.weekly), monthly_used_credits: Math.max(0, count(budget.monthly_used_credits) - refund.monthly), updated_at: now });
    if (identityRefund) {
      const identities = await lockedIdentities(trx, [first.local_id_hash, first.ip_hash], budget.daily_window_date);
      for (const identity of identities.values()) await trx(IDENTITIES).where({ id: identity.id }).update({ used_credits: Math.max(0, count(identity.used_credits) - identityRefund), updated_at: now });
    }
    return { charge_id: chargeId, actual_credits: actual, idempotent: false };
  });
}

async function releaseOperation(database, raw, now) {
  const body = request(raw, 'release_operation'); const operationId = text(body.operation_id, 'invalid_operation_id'); const reason = text(body.reason, 'invalid_release_reason', 128);
  return database.transaction(async (trx) => {
    const budget = await lockedBudget(trx, now); const row = await trx(RESERVATIONS).where({ request_id: operationId }).forUpdate().first();
    if (!row) fail(404, 'reservation_not_found'); if (row.status !== 'reserved') return reservationResponse(row, true);
    const refund = currentRefund(row, budget, count(row.reserved_credits));
    await trx(BUDGET).where({ id: budget.id }).update({ daily_used_credits: Math.max(0, count(budget.daily_used_credits) - refund.daily), weekly_used_credits: Math.max(0, count(budget.weekly_used_credits) - refund.weekly), monthly_used_credits: Math.max(0, count(budget.monthly_used_credits) - refund.monthly), updated_at: now });
    if (row.daily_window_date === budget.daily_window_date) {
      const identities = await lockedIdentities(trx, [row.local_id_hash, row.ip_hash], budget.daily_window_date);
      for (const identity of identities.values()) await trx(IDENTITIES).where({ id: identity.id }).update({ used_credits: Math.max(0, count(identity.used_credits) - count(row.reserved_credits)), updated_at: now });
    }
    const update = { status: 'released', release_reason: reason, updated_at: now }; await trx(RESERVATIONS).where({ id: row.id }).update(update); return reservationResponse({ ...row, ...update }, false);
  });
}

async function closeRequest(database, raw, now) {
  const body = request(raw, 'close_request'); const requestId = text(body.request_id, 'invalid_request_id');
  return database.transaction(async (trx) => {
    await lockedBudget(trx, now); const row = await trx(RESERVATIONS).where({ request_id: requestId }).forUpdate().first();
    if (!row || row.status !== 'request_open') fail(409, 'request_closed');
    const child = await trx(RESERVATIONS).where({ parent_request_id: requestId, status: 'reserved' }).forUpdate().first(); if (child) fail(409, 'request_has_reserved_operations');
    const update = { status: 'released', release_reason: 'closed', updated_at: now }; await trx(RESERVATIONS).where({ id: row.id }).update(update); return reservationResponse({ ...row, ...update }, false);
  });
}

export async function executeOperation(database, operation, raw, now = new Date()) {
  const handlers = { health_check: async () => { request(raw, 'health_check'); await database.raw('SELECT 1'); return { status: 'ok', protocol_version: PROTOCOL_VERSION }; }, get_status: status, save_budget: saveBudget, open_request: openRequest, reserve_operation: reserveOperation, finalize_charge: finalizeCharge, release_operation: releaseOperation, close_request: closeRequest };
  if (!handlers[operation]) fail(400, 'unsupported_operation'); return handlers[operation](database, raw, now);
}

export const testing = { caps, currentRefund, dayKeys };
