/* Internal, fail-closed endpoint for atomic encrypted Project embed revisions. */
import { createHash, timingSafeEqual } from 'node:crypto';
import { activateEmbedArchiveReader, commitEmbedRevision, finalizeEmbedArchiveCopy,
  prepareEmbedArchiveCopy, retireEmbedArchiveCopy,
  pruneEmbedArchivePayload, publishEmbedSnapshot, writeLegacyEmbed, ProtocolError } from './operations.js';

const TOKEN_HEADER = 'x-internal-service-token';
const tokenDigest = (value) => createHash('sha256').update(value, 'utf8').digest();

export function isAuthorized(headers, configuredToken) {
  if (typeof configuredToken !== 'string' || !configuredToken) return false;
  const supplied = headers?.[TOKEN_HEADER];
  if (typeof supplied !== 'string' || !supplied) return false;
  return timingSafeEqual(tokenDigest(supplied), tokenDigest(configuredToken));
}

export default {
  id: 'embed-version-transaction',
  handler: (router, { database, env, logger }) => {
    router.get('/health', (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      return res.status(200).json({ data: { status: 'ok', protocol_version: 1 } });
    });
    router.post('/', async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        logger.warn({ code: 'internal_auth_failed' }, 'Embed revision transaction rejected');
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await commitEmbedRevision(database, req.body) });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ code: error.code }, 'Embed revision transaction rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ code: 'transaction_failed' }, 'Embed revision transaction failed');
        return res.status(500).json({ error: { code: 'transaction_failed' } });
      }
    });
    router.post('/snapshots', async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await publishEmbedSnapshot(database, req.body) });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ code: error.code }, 'Embed snapshot rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ code: 'snapshot_transaction_failed' }, 'Embed snapshot transaction failed');
        return res.status(500).json({ error: { code: 'snapshot_transaction_failed' } });
      }
    });
    router.post('/legacy-embed-write', async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await writeLegacyEmbed(database, req.body) });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ code: error.code }, 'Legacy embed write rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ code: 'legacy_embed_write_failed' }, 'Legacy embed write failed');
        return res.status(500).json({ error: { code: 'legacy_embed_write_failed' } });
      }
    });
    for (const [path, operation] of [
      ['/archive-prepare', prepareEmbedArchiveCopy],
      ['/archive-retire', retireEmbedArchiveCopy],
      ['/archive-copy', finalizeEmbedArchiveCopy],
    ]) router.post(path, async (req, res) => {
      if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
        return res.status(401).json({ error: { code: 'internal_auth_failed' } });
      }
      try {
        return res.status(200).json({ data: await operation(database, req.body) });
      } catch (error) {
        if (error instanceof ProtocolError) {
          logger.warn({ code: error.code }, 'Embed archive copy rejected');
          return res.status(error.status).json({ error: { code: error.code } });
        }
        logger.error({ code: 'archive_copy_transaction_failed' }, 'Embed archive copy transaction failed');
        return res.status(500).json({ error: { code: 'archive_copy_transaction_failed' } });
      }
    });
    for (const [path, operation] of [
      ['/archive-activate', activateEmbedArchiveReader],
      ['/archive-prune', pruneEmbedArchivePayload],
    ]) {
      router.post(path, async (req, res) => {
        if (!isAuthorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) {
          return res.status(401).json({ error: { code: 'internal_auth_failed' } });
        }
        try {
          return res.status(200).json({ data: await operation(database, req.body) });
        } catch (error) {
          if (error instanceof ProtocolError) {
            logger.warn({ code: error.code }, 'Embed archive transition rejected');
            return res.status(error.status).json({ error: { code: error.code } });
          }
          logger.error({ code: 'archive_transition_failed' }, 'Embed archive transition failed');
          return res.status(500).json({ error: { code: 'archive_transition_failed' } });
        }
      });
    }
  },
};
