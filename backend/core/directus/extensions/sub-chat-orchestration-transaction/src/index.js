/*
 * Internal-only Directus endpoint for bounded sub-chat orchestration.
 * Authentication fails closed and logs contain identifiers/error codes only.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { executeOperation, SubChatOrchestrationError } from './operations.js';

const TOKEN_HEADER = 'x-internal-service-token';
const digest = (value) => createHash('sha256').update(value, 'utf8').digest();

export function isAuthorized(headers, configuredToken) {
  if (typeof configuredToken !== 'string' || !configuredToken) return false;
  const supplied = headers?.[TOKEN_HEADER];
  return typeof supplied === 'string' && supplied.length > 0
    && timingSafeEqual(digest(supplied), digest(configuredToken));
}

export default {
  id: 'sub-chat-orchestration-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Sub-chat orchestration rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await executeOperation(database, operation, req.body?.data) });
      } catch (error) {
        if (error instanceof SubChatOrchestrationError) {
          logger.warn({ operation, code: error.code }, 'Sub-chat orchestration rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Sub-chat orchestration failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      }
    });
  },
};
