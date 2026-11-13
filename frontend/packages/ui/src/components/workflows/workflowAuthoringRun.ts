// frontend/packages/ui/src/components/workflows/workflowAuthoringRun.ts
//
// Shared AI authoring run for the workflows route and the chat side panel.
// Streams /v1/workflows/input/stream (via workflowInputService), recovers the
// durable session after a dropped or stopped stream, and polls queued/saving
// sessions until they settle. Callers own their view state through handlers.

import {
  getWorkflowInstruction,
  streamWorkflowInstruction,
  type WorkflowAcceptedPreview,
  type WorkflowInputSession,
  type WorkflowInputStreamEvent
} from '../../services/workflowInputService';

/** Session statuses that are still being processed by the server. */
const PENDING_STATUSES = new Set(['running', 'queued', 'saving']);

export type WorkflowAuthoringProgress = Extract<WorkflowInputStreamEvent, { type: 'progress' }>;

export interface WorkflowAuthoringRequest {
  instruction: string;
  workflowId?: string;
  /** Resume an existing session instead of starting a new stream. */
  existingSessionId?: string;
  /** Idempotency key; reuse it when retrying an interrupted submission. */
  idempotencyKey: string;
  signal: AbortSignal;
  /** Ask the server for an unsaved draft session (status `draft`, nothing persisted). */
  draftOnly?: boolean;
  /** Chat the authoring was started from (chat Recommendation); the server bills it to that chat. */
  sourceChatId?: string;
  /** User message id of that chat turn; sent only with sourceChatId. */
  sourceMessageId?: string;
}

export interface WorkflowAuthoringHandlers {
  /** False once the caller's view or account context changed; the run then stops quietly. */
  isCurrent: () => boolean;
  isStopRequested: () => boolean;
  onStarted: (sessionId: string) => void;
  onProgress: (event: WorkflowAuthoringProgress) => void;
  onPreview: (preview: WorkflowAcceptedPreview) => void;
  /** Called once the event stream has finished (not for resumed sessions). */
  onStreamSettled: () => void;
  /** Called for each poll of a session that is still running, queued or saving. */
  onPending: (session: WorkflowInputSession) => void;
}

function pollDelay(check: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, check < 2 ? 500 : 1500));
}

async function streamSession(request: WorkflowAuthoringRequest, handlers: WorkflowAuthoringHandlers): Promise<WorkflowInputSession> {
  let startedSessionId: string | null = null;
  const onEvent = (event: WorkflowInputStreamEvent) => {
    if (!handlers.isCurrent()) return;
    if (event.type === 'started') {
      startedSessionId = event.session_id;
      handlers.onStarted(event.session_id);
    } else if (event.type === 'progress') {
      handlers.onProgress(event);
    } else if (event.type === 'preview' && event.provisional && event.validated && event.graph.version === 2) {
      handlers.onPreview(event);
    }
  };
  const options = request.draftOnly || request.sourceChatId ? {
    ...(request.draftOnly ? { draftOnly: true } : {}),
    ...(request.sourceChatId ? { sourceChatId: request.sourceChatId } : {}),
    ...(request.sourceChatId && request.sourceMessageId ? { sourceMessageId: request.sourceMessageId } : {}),
  } : undefined;
  const stream = () => streamWorkflowInstruction(request.instruction, request.workflowId, onEvent, request.signal, request.idempotencyKey, options);
  try {
    return await stream();
  } catch (streamError) {
    if (!handlers.isCurrent() || (request.signal.aborted && !handlers.isStopRequested())) throw streamError;
    if (request.signal.aborted && handlers.isStopRequested() && startedSessionId) {
      return getWorkflowInstruction(startedSessionId);
    }
    if (!startedSessionId) {
      // Reuse the same key: the server may have accepted the first request.
      try {
        return await stream();
      } catch (retryError) {
        if (!startedSessionId) throw retryError;
        return getWorkflowInstruction(startedSessionId);
      }
    }
    return getWorkflowInstruction(startedSessionId);
  }
}

/**
 * Run one authoring request to a settled session.
 * Returns null when the caller is no longer current; rethrows transport errors.
 */
export async function runWorkflowAuthoring(
  request: WorkflowAuthoringRequest,
  handlers: WorkflowAuthoringHandlers
): Promise<WorkflowInputSession | null> {
  let session: WorkflowInputSession;
  if (request.existingSessionId) {
    session = await getWorkflowInstruction(request.existingSessionId);
    if (!handlers.isCurrent()) return null;
  } else {
    session = await streamSession(request, handlers);
    if (!handlers.isCurrent()) return null;
    handlers.onStreamSettled();
  }
  let pendingChecks = 0;
  while (PENDING_STATUSES.has(session.status)) {
    if (!handlers.isCurrent()) return null;
    handlers.onPending(session);
    await pollDelay(pendingChecks++);
    if (!handlers.isCurrent()) return null;
    session = await getWorkflowInstruction(session.session_id);
  }
  if (!handlers.isCurrent()) return null;
  return session;
}
