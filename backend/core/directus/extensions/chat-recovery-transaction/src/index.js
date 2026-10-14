/*
 * Directus 11 endpoint for internal encrypted chat-recovery transactions.
 * Authentication fails closed; logs contain sanitized operation/error codes.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { executeOperation, ProtocolError } from './operations.js';

const TOKEN_HEADER = 'x-internal-service-token';
const tokenDigest = (value) => createHash('sha256').update(value, 'utf8').digest();

export function isAuthorized(headers, configuredToken) {
  if (typeof configuredToken !== 'string' || !configuredToken) return false;
  const supplied = headers?.[TOKEN_HEADER];
  if (typeof supplied !== 'string' || !supplied) return false;
  return timingSafeEqual(tokenDigest(supplied), tokenDigest(configuredToken));
}

// Fixed numeric fields only: never log the request, SQL, identifiers, or error text.
const ADMISSION_PHASES = Object.freeze([
  'validation', 'transaction_setup', 'account_chat_locks', 'fences_reads', 'proof', 'commit_result',
]);
export const FIRST_PERSONAL_PHASES = Object.freeze([
  'handler_auth', 'validation', 'transaction_setup', 'account_lock', 'protocol_read',
  'chat_lock_reads', 'chat_insert', 'chat_metadata_update',
  'canonical_preflight_read', 'message_identity_read',
  'message_insert', 'chat_version_cas',
  'preflight_schema_check', 'preflight_write',
  'post_prepare_reads', 'outbox_write', 'proof_schema_check', 'proof_protocol_read',
  'proof_message_read', 'proof_row_read', 'proof_existing_validation', 'proof_write',
  'commit_result',
]);
export function createAdmissionTimer(clock = () => performance.now(), phases = ADMISSION_PHASES,
  started = clock(), loopSample = () => performance.eventLoopUtilization()) {
  const durations = Object.fromEntries(phases.map((phase) => [`${phase}_ms`, 0]));
  let phase = phases[0];
  let phaseStarted = started;
  let failurePhase = null;
  let operationFinished = null;
  let loopStarted = null;
  if (phases === FIRST_PERSONAL_PHASES) {
    try { loopStarted = loopSample(); } catch { /* observability only */ }
  }
  const enter = (next) => {
    if (!phases.includes(next)) return;
    const at = clock();
    durations[`${phase}_ms`] += Math.max(0, at - phaseStarted);
    phase = next;
    phaseStarted = at;
  };
  const finish = (failed) => {
    const at = clock();
    durations[`${phase}_ms`] += Math.max(0, at - phaseStarted);
    const result = { ...durations, total_ms: Math.max(0, at - started), failed: Number(failed),
      terminal_phase: phases.indexOf(failed ? (failurePhase ?? phase) : phase) + 1 };
    if (phases === FIRST_PERSONAL_PHASES) {
      result.operation_total_ms = Math.max(0,
        (operationFinished ?? at) - (started + result.handler_auth_ms));
      let active = 0;
      let idle = 0;
      let observed = 0;
      if (loopStarted) {
        try {
          const loopEnded = loopSample();
          active = Math.max(0, loopEnded.active - loopStarted.active);
          idle = Math.max(0, loopEnded.idle - loopStarted.idle);
          if (Number.isFinite(active) && Number.isFinite(idle)) observed = 1;
          else { active = 0; idle = 0; }
        } catch { /* observability only */ }
      }
      result.event_loop_active_ms = active;
      result.event_loop_idle_ms = idle;
      result.event_loop_utilization_permille = observed && active + idle > 0
        ? Math.round(1000 * active / (active + idle)) : 0;
      result.event_loop_observed = observed;
    }
    return result;
  };
  return { enter, failHere: () => { failurePhase ??= phase; },
    operationDone: () => { operationFinished ??= clock(); }, finish };
}

export default {
  id: 'chat-recovery-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const handlerStarted = performance.now();
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Chat recovery transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      const timingEnabled = env.CHAT_RECOVERY_ADMISSION_TIMING_ENABLED !== 'false';
      const timing = timingEnabled && operation === 'verify_routing_admission' ? createAdmissionTimer()
        : timingEnabled && operation === 'admit_first_personal'
          ? createAdmissionTimer(() => performance.now(), FIRST_PERSONAL_PHASES, handlerStarted) : null;
      if (operation === 'admit_first_personal') timing?.enter('validation');
      let failed = true;
      try {
        const data = await executeOperation(database, operation, req.body?.data, new Date(), timing);
        timing?.operationDone();
        failed = false;
        return res.status(200).json({ data });
      } catch (error) {
        timing?.operationDone();
        if (error instanceof ProtocolError) {
          logger.warn({ operation, code: error.code }, 'Chat recovery transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Chat recovery transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      } finally {
        if (timing) {
          try { logger.info(timing.finish(failed), operation === 'admit_first_personal'
            ? 'First Personal admission timing' : 'Routing admission timing'); } catch { /* observability only */ }
        }
      }
    });
  },
};
