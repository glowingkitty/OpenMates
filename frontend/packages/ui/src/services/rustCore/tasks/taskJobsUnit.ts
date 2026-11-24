/** Worker adapter for the shared Rust Task job writer (feature.task-inline-embeds). */
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { createUnitPort, serveUnitPort, UnitRefusal } from '../host/unitPort';

export const TASK_JOBS_CLOSE = { type: 'task_jobs_close' } as const;

export type TaskJobsProtocol = {
  persist: { request: { offer: unknown; socket: MessagePort }; response: string[] };
};

export type TaskJobSocketProtocol = {
  exchange: { request: string; response: string };
};

interface TaskJobClient {
  persist_task_jobs(
    handle: string,
    generation: number,
    offer: string,
    exchange: (request: string) => Promise<string>,
  ): Promise<string>;
}

export function installTaskJobsUnit(context: UnitInstallContext): () => void {
  const { principal, ports: [port], signal: lifetime } = context;
  if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
  const stop = serveUnitPort<TaskJobsProtocol>(port, {
    async persist({ offer, socket }, signal) {
      if (!(socket instanceof MessagePort)) throw new UnitRefusal('invalid_request');
      const operation = AbortSignal.any([signal, lifetime]);
      const relay = createUnitPort<TaskJobSocketProtocol>(socket);
      try {
        const borrow = await borrowCoreClient(principal, operation, 15_000);
        if (borrow === 'none') throw new UnitRefusal('not_admitted');
        if (borrow === 'local') throw new UnitRefusal('local_session');
        if (borrow === 'busy') throw new UnitRefusal('core_busy');
        try {
          const client = borrow.client as unknown as TaskJobClient;
          const committed = await client.persist_task_jobs(
            borrow.status.handle,
            borrow.status.generation,
            JSON.stringify(offer),
            (request) => relay.request('exchange', request, { signal: operation, timeoutMs: 20_000 }),
          );
          return JSON.parse(committed) as string[];
        } catch (error) {
          throw new UnitRefusal(typeof error === 'string' ? error : 'task_job_unavailable');
        } finally {
          borrow.release();
        }
      } finally {
        relay.close();
      }
    },
  });

  function dispose(): void {
    port.removeEventListener('message', close);
    stop();
    port.close();
  }
  function close(event: MessageEvent<unknown>): void {
    if ((event.data as { type?: unknown } | null)?.type === TASK_JOBS_CLOSE.type) dispose();
  }
  port.addEventListener('message', close);
  lifetime.addEventListener('abort', dispose, { once: true });
  return dispose;
}
