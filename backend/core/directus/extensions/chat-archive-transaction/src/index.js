import { archiveMutationOperation } from './mutations.js';
/* Internal only. Clients use owner/Team-authorized API message windows. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { archiveOperation, ArchiveProtocolError } from './operations.js';

export function isAuthorized(headers, token) {
  const value = headers?.['x-internal-service-token'];
  if (typeof token !== 'string' || !token || typeof value !== 'string' || !value) return false;
  const digest = (text) => createHash('sha256').update(text).digest();
  return timingSafeEqual(digest(value), digest(token));
}

export default {
  id: 'chat-archive-transaction',
  handler(router, { database, env, logger }) {
    router.post('/', async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        const data = await (['restore_and_retire_page', 'lookup_mutation_page', 'abort_unpublished_page'].includes(req.body?.operation) ? archiveMutationOperation(database, req.body) : archiveOperation(database, req.body));
        return res.status(200).json({ data });
      } catch (error) {
        const known = error instanceof ArchiveProtocolError;
        logger.warn({ code: known ? error.code : 'archive_transaction_failed' }, 'Archive transaction rejected');
        return res.status(known ? error.status : 500).json({ error: { code: known ? error.code : 'archive_transaction_failed' } });
      }
    });
  },
};
