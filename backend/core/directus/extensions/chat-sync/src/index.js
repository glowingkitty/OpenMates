/**
 * Internal chat sync feed endpoints and one PostgreSQL commit listener.
 * Notifications carry a hashed scope and revision only; they are coalesced
 * per scope and forwarded to the API, which hints authorized sockets. A lost
 * hint only delays delivery: clients replay the durable log from their cursor.
 * Public clients cannot call these internal endpoints (shared service token).
 * Spec: specifications/architecture/sync/specification.yml.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { pruneExpired, readChanges, readClock, readOverview } from './operations.js';

const digest = value => createHash('sha256').update(value).digest();
const NOTIFICATION = /^((?:personal|team|user):[0-9a-f]{64})\|(\d{1,19})$/;
const PRUNE_INTERVAL_MS = 60 * 60 * 1000;

export function authorized(headers, configured) {
  const supplied = headers?.['x-internal-service-token'];
  return typeof configured === 'string' && configured.length > 0 && typeof supplied === 'string'
    && timingSafeEqual(digest(supplied), digest(configured));
}

/** Keep the highest revision per scope; returns false for foreign payloads. */
export function coalesceNotification(pending, payload) {
  const match = NOTIFICATION.exec(payload ?? '');
  if (!match) return false;
  const [, scope, revision] = match;
  const previous = pending.get(scope);
  if (previous === undefined || BigInt(revision) > BigInt(previous)) {
    if (previous === undefined && pending.size >= 10000) return false;
    pending.set(scope, revision);
  }
  return true;
}

function listenForCommits(database, env, logger) {
  let timer;
  const pending = new Map();
  let sending = false;
  async function sendHints() {
    timer = undefined;
    if (sending || !pending.size) return;
    sending = true;
    const hints = [...pending.entries()].slice(0, 500).map(([scope, revision]) => ({ scope, revision }));
    hints.forEach(({ scope }) => pending.delete(scope));
    try {
      const response = await fetch(env.CHAT_SYNC_NOTIFY_URL || 'http://api:8000/internal/chat-sync/changed', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Internal-Service-Token': env.INTERNAL_API_SHARED_TOKEN },
        body: JSON.stringify({ hints }), signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error('chat_sync_hint_rejected');
    } catch {
      for (const { scope, revision } of hints) coalesceNotification(pending, `${scope}|${revision}`);
      logger.warn({ code: 'chat_sync_hint_deferred' }, 'Chat sync notification deferred');
    } finally {
      sending = false;
      if (pending.size) timer = setTimeout(sendHints, 2000).unref();
    }
  }
  async function connect() {
    let connection;
    try {
      connection = await database.client.acquireRawConnection();
      await connection.query('LISTEN openmates_chat_sync');
      await new Promise((resolve, reject) => {
        connection.on('notification', message => {
          if (message.channel !== 'openmates_chat_sync' || !coalesceNotification(pending, message.payload)) return;
          if (!sending && !timer) timer = setTimeout(sendHints, 50).unref();
        });
        connection.once('error', reject);
        connection.once('end', resolve);
      });
    } catch {
      logger.warn({ code: 'chat_sync_listener_reconnecting' }, 'Chat sync commit listener reconnecting');
    } finally {
      if (connection) await database.client.destroyRawConnection(connection).catch(() => undefined);
      setTimeout(connect, 2000).unref();
    }
  }
  void connect();
}

function schedulePruning(database, logger) {
  const prune = async () => {
    try { await pruneExpired(database); }
    catch { logger.warn({ code: 'chat_sync_prune_deferred' }, 'Chat sync retention deferred'); }
  };
  setInterval(prune, PRUNE_INTERVAL_MS).unref();
}

function route(router, path, operation, env, logger) {
  router.post(path, async (req, res) => {
    if (!authorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) return res.status(401).json({ error: 'internal_auth_failed' });
    try {
      return res.json({ data: await operation(req.body) });
    } catch (error) {
      const invalid = error.message === 'invalid_sync_scope';
      logger.warn({ code: invalid ? 'invalid_sync_scope' : 'chat_sync_read_failed' }, 'Chat sync read rejected');
      return res.status(invalid ? 400 : 503).json({ error: invalid ? 'invalid_sync_scope' : 'chat_sync_read_failed' });
    }
  });
}

export default {
  id: 'chat-sync',
  handler(router, { database, env, logger }) {
    listenForCommits(database, env, logger);
    schedulePruning(database, logger);
    route(router, '/changes', body => readChanges(database, body), env, logger);
    route(router, '/clock', body => readClock(database, body), env, logger);
    route(router, '/overview', body => readOverview(database, body), env, logger);
  },
};
