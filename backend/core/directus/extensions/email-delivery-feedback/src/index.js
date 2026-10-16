// Internal CMS only. CMS is not publicly routed; require Directus admin auth.
import { FeedbackError, updateSuppression } from './operations.js';

export default {
  id: 'email-delivery-feedback',
  handler: (router, {database, logger}) => {
    router.post('/', async (req, res) => {
      if (req.accountability?.admin !== true) return res.status(403).json({error: {code: 'admin_required'}});
      try {
        return res.status(200).json({data: await updateSuppression(database, req.body)});
      } catch (error) {
        if (error instanceof FeedbackError) return res.status(error.status).json({error: {code: error.code}});
        // SQL/error text may contain private metadata; record a bounded code.
        logger.error({code: 'email_feedback_update_failed'}, 'Email feedback update failed');
        return res.status(500).json({error: {code: 'update_failed'}});
      }
    });
  },
};
