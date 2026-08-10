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

export default {
  id: 'chat-recovery-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Chat recovery transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await executeOperation(database, operation, req.body?.data) });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ operation, code: error.code }, 'Chat recovery transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Chat recovery transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      }
    });
  },
};
