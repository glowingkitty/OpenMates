/* Private workflow authoring commit boundary. No user plaintext enters Directus. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { executeAuthoring, AuthoringError } from './operations.js';

const digest = (value) => createHash('sha256').update(value, 'utf8').digest();
const authorized = (headers, token) => typeof token === 'string' && token.length > 0
  && typeof headers?.['x-internal-service-token'] === 'string'
  && timingSafeEqual(digest(headers['x-internal-service-token']), digest(token));

export default {
  id: 'workflow-authoring-transaction',
  handler: (router, { database, env, logger }) => {
    for (const path of ['/health', '/receipt', '/operation', '/', '/run-status', '/legacy-head', '/expire-temporary', '/purge-chat-embed', '/prune-mutations']) {
      router.post(path, async (req, res) => {
        if (!authorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
          return res.status(401).json({ error: { code: 'internal_auth_failed' } });
        }
        try {
          return res.status(200).json({ data: await executeAuthoring(database, path, req.body) });
        } catch (error) {
          if (error instanceof AuthoringError) {
            return res.status(error.status).json({ error: { code: error.code } });
          }
          if (error?.code === '23505') {
            return res.status(409).json({ error: { code: 'unique_conflict' } });
          }
          logger.error({ path, code: 'transaction_failed' }, 'Workflow authoring transaction failed');
          return res.status(500).json({ error: { code: 'transaction_failed' } });
        }
      });
    }
  },
};
