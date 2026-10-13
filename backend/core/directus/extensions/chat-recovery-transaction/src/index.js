/*
 * Directus 11 endpoint for internal encrypted chat-recovery transactions.
 * Authentication fails closed; logs contain sanitized operation/error codes.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
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
export function createAdmissionTimer(clock = () => performance.now()) {
  const durations = Object.fromEntries(ADMISSION_PHASES.map((phase) => [`${phase}_ms`, 0]));
  const started = clock();
  let phase = 'validation';
  let phaseStarted = started;
  let failurePhase = null;
  const enter = (next) => {
    if (!ADMISSION_PHASES.includes(next)) return;
    const at = clock();
    durations[`${phase}_ms`] += Math.max(0, at - phaseStarted);
    phase = next;
    phaseStarted = at;
  };
  const finish = (failed) => {
    const at = clock();
    durations[`${phase}_ms`] += Math.max(0, at - phaseStarted);
    return { ...durations, total_ms: Math.max(0, at - started), failed: Number(failed),
      terminal_phase: ADMISSION_PHASES.indexOf(failed ? (failurePhase ?? phase) : phase) + 1 };
  };
  return { enter, failHere: () => { failurePhase ??= phase; }, finish };
}

export default {
  id: 'chat-recovery-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Chat recovery transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      const timing = operation === 'verify_routing_admission'
        && env.CHAT_RECOVERY_ADMISSION_TIMING_ENABLED !== 'false' ? createAdmissionTimer() : null;
      let failed = true;
      try {
        const data = await executeOperation(database, operation, req.body?.data, new Date(), timing);
        failed = false;
        return res.status(200).json({ data });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ operation, code: error.code }, 'Chat recovery transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Chat recovery transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      } finally {
        if (timing) {
          try { logger.info(timing.finish(failed), 'Routing admission timing'); } catch { /* observability only */ }
        }
      }
    });
  },
};
