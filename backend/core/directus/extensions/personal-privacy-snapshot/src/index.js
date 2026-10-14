import { createHash, timingSafeEqual } from 'node:crypto';
import { readPersonalPrivacySnapshot } from './operations.js';
const digest = value => createHash('sha256').update(value).digest();
export function authorized(headers, configured) {
  const supplied = headers?.['x-internal-service-token'];
  return typeof configured === 'string' && configured.length > 0 && typeof supplied === 'string'
    && timingSafeEqual(digest(supplied), digest(configured));
}
// Internal-only service endpoint. No developer/public API or client credentials.
export default {id:'personal-privacy-snapshot', handler(router,{database,env,logger}) {
  router.post('/', async (req,res) => {
    if (!authorized(req.headers,env.INTERNAL_API_SHARED_TOKEN)) return res.status(401).json({error:'internal_auth_failed'});
    try { return res.json({data:await readPersonalPrivacySnapshot(database,req.body)}); }
    catch (error) {
      logger.warn({code:'personal_privacy_snapshot_unavailable'},'Personal privacy snapshot unavailable');
      return res.status(error.message === 'invalid_snapshot_request' ? 400 : 503).json({error:'snapshot_unavailable'});
    }
  });
}};
