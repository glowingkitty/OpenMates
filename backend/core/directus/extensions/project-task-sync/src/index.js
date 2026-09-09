/**
 * Internal Project Task replay endpoint and one PostgreSQL commit listener.
 * Notifications carry workspace hashes only and are coalesced before delivery.
 * Failed hints are safe: the durable cursor is reconciled on reconnect/heartbeat.
 * Public clients cannot call this internal transaction endpoint.
 * See docs/plans/codex-tasks-orchestration/codex-rebuild-architecture.md.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { readProjectChanges } from './operations.js';
const digest = value => createHash('sha256').update(value).digest();

export function authorized(headers, configured) {
  const supplied = headers?.['x-internal-service-token'];
  return typeof configured === 'string' && configured.length > 0 && typeof supplied === 'string'
    && timingSafeEqual(digest(supplied), digest(configured));
}

function listenForCommits(database, env, logger) {
  let timer;
  const pending = new Set();
  let sending = false;
  async function sendHints() {
    timer = undefined;
    if (sending || !pending.size) return;
    sending = true;
    const scopes = [...pending].slice(0, 500);
    scopes.forEach(scope => pending.delete(scope));
    try {
      const response = await fetch(env.TASK_SYNC_NOTIFY_URL || 'http://api:8000/internal/task-sync/changed', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Internal-Service-Token': env.INTERNAL_API_SHARED_TOKEN },
        body: JSON.stringify({ scopes }), signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error('task_sync_hint_rejected');
    } catch {
      // Bounded transient hints are not the durable replay ledger.
      for (const scope of scopes) if (pending.size < 10000) pending.add(scope);
      logger.warn({ code: 'task_sync_hint_deferred' }, 'Task sync notification deferred');
    } finally {
      sending = false;
      if (pending.size) timer = setTimeout(sendHints, 2000).unref();
    }
  }
  async function connect() {
    let connection;
    try {
      connection = await database.client.acquireRawConnection();
      await connection.query('LISTEN openmates_task_sync');
      await new Promise((resolve, reject) => {
        connection.on('notification', message => {
          if (message.channel !== 'openmates_task_sync' || !/^(personal|team):[0-9a-f]{64}$/.test(message.payload ?? '')) return;
          if (pending.size < 10000) pending.add(message.payload);
          if (!sending && !timer) timer = setTimeout(sendHints, 50).unref();
        });
        connection.once('error', reject);
        connection.once('end', resolve);
      });
    } catch {
      logger.warn({ code: 'task_sync_listener_reconnecting' }, 'Task sync commit listener reconnecting');
    } finally {
      if (connection) await database.client.destroyRawConnection(connection).catch(() => undefined);
      setTimeout(connect, 2000).unref();
    }
  }
  void connect();
}

export default {
  id: 'project-task-sync',
  handler(router, { database, env, logger }) {
    listenForCommits(database, env, logger);
    router.post('/', async (req, res) => {
      if (!authorized(req.headers, env.INTERNAL_API_SHARED_TOKEN)) return res.status(401).json({ error: 'internal_auth_failed' });
      try {
        return res.json({ data: await readProjectChanges(database, req.body) });
      } catch (error) {
        const invalid = error.message === 'invalid_sync_scope';
        logger.warn({ code: invalid ? 'invalid_sync_scope' : 'task_sync_read_failed' }, 'Task sync read rejected');
        return res.status(invalid ? 400 : 503).json({ error: invalid ? 'invalid_sync_scope' : 'task_sync_read_failed' });
      }
    });
  },
};
