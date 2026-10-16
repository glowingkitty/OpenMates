/* Internal-only, read-only storage usage endpoint. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { listPersonalOwnerIds, MeteringError, quoteUsage, uploadBreakdown } from './quote.js';

export function isAuthorized(headers, configuredToken) {
  const supplied = headers?.['x-internal-service-token'];
  if (typeof configuredToken !== 'string' || !configuredToken
      || typeof supplied !== 'string' || !supplied) return false;
  const digest = (value) => createHash('sha256').update(value).digest();
  return timingSafeEqual(digest(configuredToken), digest(supplied));
}

export default {
  id: 'storage-usage-metering',
  handler(router, { database, env, logger }) {
    router.post('/', async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        const body = req.body ?? {};
        const data = body.operation === 'quote'
          ? await quoteUsage(database, body)
          : body.operation === 'list_personal_owners'
            ? await listPersonalOwnerIds(database, body)
            : body.operation === 'upload_breakdown'
              ? await uploadBreakdown(database, body)
            : (() => { throw new MeteringError(400, 'invalid_operation'); })();
        return res.status(200).json({ data });
      } catch (error) {
        const known = error instanceof MeteringError;
        logger.warn({ code: known ? error.code : 'storage_metering_failed' }, 'Storage metering rejected');
        return res.status(known ? error.status : 500)
          .json({ error: { code: known ? error.code : 'storage_metering_failed' } });
      }
    });
  },
};
