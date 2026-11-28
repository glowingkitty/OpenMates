import type { Page } from '@playwright/test';

/** Observe the real persistence receipt without intercepting any application traffic. */
export function observeTaskJobPersistence(page: Page) {
  const offers = new Map<string, string>();
  const committed = new Map<string, string>();
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).pathname !== '/v1/ws') return;
    socket.on('framereceived', ({ payload }) => {
      if (typeof payload !== 'string') return;
      const frame = JSON.parse(payload);
      if (frame.type === 'task_update_jobs_available') {
        for (const job of frame.payload.jobs) offers.set(job.job_id, job.chat_id);
      }
      if (frame.type === 'task_update_job_persisted' && ['TASK_PERSISTED', 'TERMINAL'].includes(frame.payload.state)) {
        const { job_id, task_id } = frame.payload;
        if (offers.has(job_id) && typeof task_id === 'string') committed.set(job_id, task_id);
      }
    });
  });
  return (chatId: string) => [...committed].filter(([job]) => offers.get(job) === chatId).map(([, task]) => task);
}
