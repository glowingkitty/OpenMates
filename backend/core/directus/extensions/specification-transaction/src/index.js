/* Internal-only transaction transport; error messages never include ciphertext. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { executeSpecification, SpecificationError } from './operations.js';

const digest = (value) => createHash('sha256').update(value, 'utf8').digest();
export default {
  id: 'specification-transaction',
  handler: (router, { database, env, logger }) => {
    router.post('/', async (req, res) => {
      const supplied = req.headers?.['x-internal-service-token'];
      const expected = env.INTERNAL_API_SHARED_TOKEN;
      if (typeof supplied !== 'string' || typeof expected !== 'string' || !expected
          || !timingSafeEqual(digest(supplied), digest(expected))) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await executeSpecification(database, req.body) });
      } catch (error) {
        if (error instanceof SpecificationError) return res.status(error.status).json({ error: { code: error.code } });
        if (error?.code === '23505') return res.status(409).json({ error: { code: 'revision_conflict' } });
        logger.error({ code: 'specification_transaction_failed' }, 'Specification transaction failed');
        return res.status(500).json({ error: { code: 'specification_transaction_failed' } });
      }
    });
  },
};
