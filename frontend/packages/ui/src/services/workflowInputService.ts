import { workflowApiFetch, workflowApiRequest, type WorkflowDetail, type WorkflowGraph, type WorkflowNode } from '../stores/workflowWorkspaceStore';
import { buildWorkBody, workClient, workDecide, type WorkRequest } from './work/workRust';
import type { WorkClient } from './rustCore/crypto/workOps';

// Flag-on builds decide session paths, the instruction body and the session
// normalization of request replies in the shared Rust core Worker (`work` op,
// web_work/workflows.rs + workflow_bodies.rs); the constant folds to false
// otherwise. SSE parsing (and the per-event normalization inside it, which is
// synchronous) stays here.
const RUST_WORK = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/** Flag on: the Worker's `normalizeSession` (answered in the reply's own key order). */
async function normalizedWork(work: WorkClient, session: WorkflowInputSession): Promise<WorkflowInputSession> {
  return (await workDecide<{ session: WorkflowInputSession }>(work, 'workflowInputSession', { session })).session;
}

/** Flag on: an instruction request (path and ordered body) decided in the Worker. */
async function instructionWork(work: WorkClient, route: 'input' | 'stream', text: string, selectedWorkflowId?: string, idempotencyKey?: string, draftOnly?: boolean): Promise<{ path: string; body: string }> {
  const request = await workDecide<WorkRequest>(work, 'workflowInputBody', {
    route, text, selected_workflow_id: selectedWorkflowId, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, idempotency_key: idempotencyKey, ...(draftOnly ? { draft_only: true } : {}),
  });
  return { path: request.path, body: JSON.stringify(await buildWorkBody(request.steps, {}, {})) };
}

/** Flag on: one session request (`get`, `stop`, `undo`) with its Worker path and normalized reply. */
async function sessionWork(work: WorkClient, route: 'get' | 'stop' | 'undo', sessionId: string): Promise<WorkflowInputSession> {
  const path = await workDecide<string>(work, 'workflowInputPath', { route, session_id: sessionId });
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(path, route === 'get' ? undefined : { method: 'POST', body: '{}' });
  return normalizedWork(work, result.session);
}

export type WorkflowInputChange = {
  workflow_id: string;
  added_node_ids: string[];
  edited_node_ids: string[];
  removed_nodes: Array<{ id: string; title: string }>;
  operation?: 'create' | 'update';
  changed_node_ids?: string[];
  removed_node_ids?: string[];
};

export type WorkflowAcceptedPreview = {
  workflow_index: number;
  operation?: 'create' | 'update';
  graph: WorkflowGraph;
  metadata: { title: string; description?: string | null; category?: string; icon?: string; action?: string; workflow_id?: string; assumptions?: string[] };
  accepted_node_count?: number;
  node?: WorkflowNode;
};

export type WorkflowInputSession = {
  session_id: string;
  status: string;
  message?: string | null;
  error?: string | null;
  error_code?: string | null;
  partial_reason?: 'stopped' | 'provider_error' | string | null;
  partial_warning?: string | null;
  stop_requested?: boolean;
  workflow?: WorkflowDetail | null;
  preview_workflow?: WorkflowDetail | null;
  preview_workflows?: WorkflowDetail[];
  partial_previews?: WorkflowAcceptedPreview[];
  // The batch service will populate these only after its atomic commit.
  workflows?: WorkflowDetail[];
  changes?: WorkflowInputChange[];
  assumptions?: string[];
  undo_available?: boolean;
  mutations?: Array<{ type: 'create_workflow' | 'update_workflow' | 'link_workflow_to_project'; target_id: string; before?: { graph?: { nodes?: WorkflowNode[] } } | null; after?: { graph?: { nodes?: WorkflowNode[] } } | null }>;
};

export type WorkflowInputStreamEvent =
  | { type: 'started'; session_id: string; status: 'running' }
  | { type: 'progress'; phase: 'planning' | 'validating' | 'retrying_node' | 'saving'; message?: string; workflow_index?: number; node_index?: number; operation?: 'create' | 'update' | 'mixed'; workflow_count?: number }
  | ({ type: 'preview'; provisional: true; validated: true } & WorkflowAcceptedPreview)
  | { type: 'session'; session: WorkflowInputSession };

function normalizeSession(session: WorkflowInputSession): WorkflowInputSession {
  if (!session.changes?.length) return session;
  return {
    ...session,
    changes: session.changes.map(change => {
      const before = session.mutations?.find(item => item.target_id === change.workflow_id)?.before?.graph?.nodes ?? [];
      return {
        ...change,
        added_node_ids: change.added_node_ids ?? [],
        edited_node_ids: change.edited_node_ids ?? change.changed_node_ids ?? [],
        removed_nodes: change.removed_nodes ?? (change.removed_node_ids ?? []).map(id => {
          const node = before.find(item => item.id === id);
          return { id, title: node?.title || node?.type.replace(/_/g, ' ') || id };
        })
      };
    })
  };
}

function instructionBody(text: string, selectedWorkflowId?: string, idempotencyKey?: string): string {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return JSON.stringify({ text, input_type: 'text', selected_workflow_id: selectedWorkflowId ?? null, timezone, optimistic_save: true, ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}) });
}

/** Reads SSE incrementally; a server can split UTF-8, lines, and events across chunks. */
export async function streamWorkflowInstruction(
  text: string,
  selectedWorkflowId: string | undefined,
  onEvent: (event: WorkflowInputStreamEvent) => void,
  signal?: AbortSignal,
  idempotencyKey?: string,
  options?: { draftOnly?: boolean },
): Promise<WorkflowInputSession> {
  // draftOnly is decided only in the Rust core Worker; no TypeScript twin exists.
  if (options?.draftOnly && !RUST_WORK) throw new Error('draftOnly requires the Rust core');
  const work = RUST_WORK ? workClient() : null;
  const request = work
    ? await instructionWork(work, 'stream', text, selectedWorkflowId, idempotencyKey, options?.draftOnly)
    : { path: '/v1/workflows/input/stream', body: instructionBody(text, selectedWorkflowId, idempotencyKey) };
  const response = await workflowApiFetch(request.path, {
    method: 'POST', body: request.body
  }, 'text/event-stream', signal);
  if (!response.body) throw new Error('Workflow stream is unavailable.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let dataLines: string[] = [];
  let finalSession: WorkflowInputSession | null = null;
  const dispatch = () => {
    if (!dataLines.length) return;
    const event = JSON.parse(dataLines.join('\n')) as WorkflowInputStreamEvent;
    dataLines = [];
    if (event.type === 'session') {
      event.session = normalizeSession(event.session);
      finalSession = event.session;
    }
    onEvent(event);
  };
  const consume = (flush = false) => {
    while (true) {
      const newline = buffer.indexOf('\n');
      if (newline < 0) break;
      const line = buffer.slice(0, newline).replace(/\r$/, '');
      buffer = buffer.slice(newline + 1);
      if (!line) dispatch();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    }
    if (flush) {
      if (buffer.startsWith('data:')) dataLines.push(buffer.slice(5).trimStart());
      dispatch();
    }
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      consume();
    }
    buffer += decoder.decode();
    consume(true);
  } finally {
    reader.releaseLock();
  }
  if (!finalSession) throw new Error('Workflow stream ended before a result was received.');
  return finalSession;
}

export function committedWorkflows(session: WorkflowInputSession): WorkflowDetail[] {
  if (session.status !== 'executed' && !(session.status === 'draft' && session.partial_reason)) return [];
  return session.workflows ?? (session.workflow ? [session.workflow] : []);
}

export async function stopWorkflowInstruction(sessionId: string): Promise<WorkflowInputSession> {
  const work = RUST_WORK ? workClient() : null;
  if (work) return sessionWork(work, 'stop', sessionId);
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/stop`, {
    method: 'POST', body: '{}'
  });
  return normalizeSession(result.session);
}

export function workflowNodeChanges(before: WorkflowNode[], after: WorkflowNode[]): Omit<WorkflowInputChange, 'workflow_id'> {
  const previous = new Map(before.map(node => [node.id, node]));
  const current = new Map(after.map(node => [node.id, node]));
  return {
    added_node_ids: after.filter(node => !previous.has(node.id)).map(node => node.id),
    edited_node_ids: after.filter(node => {
      const old = previous.get(node.id);
      return old !== undefined && JSON.stringify(old) !== JSON.stringify(node);
    }).map(node => node.id),
    removed_nodes: before.filter(node => !current.has(node.id)).map(node => ({ id: node.id, title: node.title || node.type.replace(/_/g, ' ') }))
  };
}

export async function submitWorkflowInstruction(text: string, selectedWorkflowId?: string): Promise<WorkflowInputSession> {
  const work = RUST_WORK ? workClient() : null;
  if (work) {
    const request = await instructionWork(work, 'input', text, selectedWorkflowId);
    const decided = await workflowApiRequest<{ session: WorkflowInputSession }>(request.path, { method: 'POST', body: request.body });
    return normalizedWork(work, decided.session);
  }
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>('/v1/workflows/input', {
    method: 'POST',
    body: instructionBody(text, selectedWorkflowId)
  });
  return normalizeSession(result.session);
}

export async function undoWorkflowInstruction(sessionId: string): Promise<WorkflowInputSession> {
  const work = RUST_WORK ? workClient() : null;
  if (work) return sessionWork(work, 'undo', sessionId);
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/undo`, {
    method: 'POST', body: '{}'
  });
  return normalizeSession(result.session);
}

export async function getWorkflowInstruction(sessionId: string): Promise<WorkflowInputSession> {
  const work = RUST_WORK ? workClient() : null;
  if (work) return sessionWork(work, 'get', sessionId);
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}`);
  return normalizeSession(result.session);
}
