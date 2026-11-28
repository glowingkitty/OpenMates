/** Relay Task job offers and correlated receipts between the socket and Rust. */
import { setTaskUpdateJobsCapabilityEnabled } from '../../../config/api';
import { refreshTaskViewsAfterJob } from '../../userTaskService';
import { getWorkspaceCacheIdentity } from '../../workspaceQueryCache';
import { webSocketService } from '../../websocketService';
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, serveUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { withServerSession } from '../projects/projectTimelineClient';
import { TASK_JOBS_CLOSE, type TaskJobsProtocol, type TaskJobSocketProtocol } from './taskJobsUnit';

interface SocketFrame {
  type: string;
  payload: Record<string, unknown>;
}

interface SocketRequest {
  frame: SocketFrame;
  reply: string;
  field: string;
  id: string;
}

function exchange(request: string, connection: object, signal: AbortSignal): Promise<string> {
  const { frame, reply, field, id } = JSON.parse(request) as SocketRequest;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    function cleanup(): void {
      webSocketService.removeEventListener('message', listener);
      signal.removeEventListener('abort', abort);
    }
    function abort(): void {
      cleanup();
      reject(new Error('cancelled'));
    }
    function listener(event: Event): void {
      const result = (event as CustomEvent<SocketFrame>).detail;
      if (webSocketService.getConnectionForSend() !== connection) {
        abort();
        return;
      }
      if ((result.type !== reply && result.type !== 'error') || result.payload?.[field] !== id) return;
      cleanup();
      resolve(JSON.stringify(result));
    }
    signal.addEventListener('abort', abort, { once: true });
    webSocketService.addEventListener('message', listener);
    void webSocketService.sendMessage(frame.type, frame.payload, { expectedConnection: connection })
      .catch((error: unknown) => {
        cleanup();
        reject(error);
      });
  });
}

interface OpenTaskJobs {
  core: SharedRustCore;
  generation: number;
  port: MessagePort;
  unit: UnitPort<TaskJobsProtocol>;
}

/** Register before opening the socket so reconnect inventories are delivered. */
export function installTaskJobRunner(): () => void {
  const lifetime = new AbortController();
  let queue = Promise.resolve();
  let opened: OpenTaskJobs | undefined;

  function closeUnit(): void {
    if (!opened) return;
    if (!opened.unit.closed) opened.port.postMessage(TASK_JOBS_CLOSE);
    opened.unit.close();
    opened = undefined;
  }

  async function jobUnit(): Promise<UnitPort<TaskJobsProtocol>> {
    const core = await whenSharedRustCore({ timeoutMs: 15_000, signal: lifetime.signal });
    const generation = core.generation;
    if (generation === null) throw new UnitPortError('not_admitted');
    if (opened?.core === core && opened.generation === generation && !opened.unit.closed) return opened.unit;

    closeUnit();
    const port = await core.openUnit('taskJobs', { signal: lifetime.signal });
    const unit = createUnitPort<TaskJobsProtocol>(port);
    opened = { core, generation, port, unit };
    return unit;
  }

  async function persist(offer: unknown, connection: object): Promise<void> {
    lifetime.signal.throwIfAborted();
    if (webSocketService.getConnectionForSend() !== connection) return;
    const scope = getWorkspaceCacheIdentity();
    const unit = await jobUnit();
    const socket = new MessageChannel();
    const stop = serveUnitPort<TaskJobSocketProtocol>(socket.port1, {
      exchange: (request, signal) => exchange(request, connection, AbortSignal.any([signal, lifetime.signal])),
    });
    try {
      const tasks = await unit.request('persist', { offer, socket: socket.port2 }, {
        transfer: [socket.port2],
        signal: lifetime.signal,
        timeoutMs: 140_000,
      });
      refreshTaskViewsAfterJob(tasks, scope);
    } finally {
      stop();
      socket.port1.close();
    }
  }

  function onOffer(offer: unknown): void {
    const connection = webSocketService.getConnectionForSend();
    if (!connection) return;
    queue = queue
      .then(() => withServerSession(() => persist(offer, connection)))
      .catch((error: unknown) => {
        if (!lifetime.signal.aborted) {
          console.warn('[TaskJobs] Could not persist offered Tasks', error instanceof UnitPortError ? error.code : 'unavailable');
        }
      });
  }

  webSocketService.on('task_update_jobs_available', onOffer);
  setTaskUpdateJobsCapabilityEnabled(true);
  if (webSocketService.isConnectedOrConnecting()) webSocketService.forceReconnect('Task job runner installed');
  return () => {
    lifetime.abort();
    closeUnit();
    setTaskUpdateJobsCapabilityEnabled(false);
    webSocketService.off('task_update_jobs_available', onOffer);
  };
}
