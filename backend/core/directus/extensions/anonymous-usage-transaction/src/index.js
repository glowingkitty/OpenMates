/*
 * Internal-only Directus endpoint for atomic anonymous usage accounting.
 * It accepts only the shared internal service token and never logs identities.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { AnonymousUsageError, executeOperation } from './operations.js';

const TOKEN_HEADER = 'x-internal-service-token';
const digest = (value) => createHash('sha256').update(value, 'utf8').digest();

export function isAuthorized(headers, configuredToken) {
  if (typeof configuredToken !== 'string' || !configuredToken) return false;
  const supplied = headers?.[TOKEN_HEADER];
  return typeof supplied === 'string' && supplied.length > 0
    && timingSafeEqual(digest(supplied), digest(configuredToken));
}

export default {
  id: 'anonymous-usage-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Anonymous usage transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await executeOperation(database, operation, req.body?.data) });
      } catch (error) {
        if (error instanceof AnonymousUsageError) {
          logger.warn({ operation, code: error.code }, 'Anonymous usage transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Anonymous usage transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      }
    });
  },
};
