/* Internal transactional claim and event-acceptance endpoint for Workflows V1. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { executeOperation, WorkflowRuntimeError } from './operations.js';

const TOKEN_HEADER = 'x-internal-service-token';
const digest = (value) => createHash('sha256').update(value, 'utf8').digest();

export function isAuthorized(headers, configuredToken) {
  if (typeof configuredToken !== 'string' || !configuredToken) return false;
  const supplied = headers?.[TOKEN_HEADER];
  return typeof supplied === 'string' && supplied.length > 0
    && timingSafeEqual(digest(supplied), digest(configuredToken));
}

export default {
  id: 'workflow-runtime-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const operation = typeof req.body?.operation === 'string' ? req.body.operation : 'invalid';
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ operation, code: 'internal_auth_failed' }, 'Workflow runtime transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await executeOperation(database, operation, req.body?.data) });
      } catch (error) {
        if (error instanceof WorkflowRuntimeError) {
          logger.warn({ operation, code: error.code }, 'Workflow runtime transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ operation, code: 'transaction_failed' }, 'Workflow runtime transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      }
    });
  },
};
