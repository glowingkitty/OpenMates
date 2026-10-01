import { getApiEndpoint } from '../config/api';
import type { WorkflowRunDetail } from '../stores/workflowWorkspaceStore';

export interface WorkflowPreviewEmbed {
  embed_id: string;
  content_type: string;
  app_id: string;
  skill_id: string;
  content: Record<string, unknown>;
}

export type WorkflowTestStreamEvent =
  | { type: 'processing'; run_id?: string }
  | { type: 'chunk'; content: string }
  | { type: 'embeds'; embeds: WorkflowPreviewEmbed[] }
  | { type: 'completed'; run: WorkflowRunDetail }
  | { type: 'error'; message: string; code?: string; run?: WorkflowRunDetail };

/** Parse SSE frames across arbitrary UTF-8/network boundaries, including CRLF. */
export async function consumeWorkflowTestStream(
  body: ReadableStream<Uint8Array>, onEvent: (event: WorkflowTestStreamEvent) => void,
): Promise<WorkflowRunDetail> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let completed: WorkflowRunDetail | null = null;
  function consumeFrame(frame: string): void {
    const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data || data === '[DONE]') return;
    const event = JSON.parse(data) as WorkflowTestStreamEvent;
    if (event.type === 'completed') completed = event.run;
    onEvent(event);
    if (event.type === 'error') throw new Error(event.message);
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      pending = pending.replace(/\r\n/g, '\n');
      let boundary: number;
      while ((boundary = pending.indexOf('\n\n')) >= 0) {
        consumeFrame(pending.slice(0, boundary));
        pending = pending.slice(boundary + 2);
      }
      if (done) { if (pending.trim()) consumeFrame(pending); break; }
      if (pending.length > 1_000_000) throw new Error('Workflow test response exceeded its stream limit.');
    }
    if (!completed) throw new Error('Workflow test connection ended before completion.');
    return completed;
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function streamWorkflowStepTest(
  path: string, input: Record<string, unknown>, onEvent: (event: WorkflowTestStreamEvent) => void, signal: AbortSignal,
): Promise<WorkflowRunDetail> {
  const response = await fetch(getApiEndpoint(path), {
    method: 'POST', credentials: 'include', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ ...input, stream: true }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message ?? `Workflow test failed with HTTP ${response.status}`);
  }
  if (!response.body) throw new Error('Workflow test response stream is unavailable.');
  return consumeWorkflowTestStream(response.body, onEvent);
}
