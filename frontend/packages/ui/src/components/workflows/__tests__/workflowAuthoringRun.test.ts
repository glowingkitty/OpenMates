// Shared workflow AI authoring run: stream, retry, stop recovery and polling.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WorkflowInputSession, WorkflowInputStreamEvent } from '../../../services/workflowInputService';

const service = vi.hoisted(() => ({
  streamWorkflowInstruction: vi.fn(),
  getWorkflowInstruction: vi.fn()
}));
vi.mock('../../../services/workflowInputService', () => service);

import { runWorkflowAuthoring, type WorkflowAuthoringHandlers, type WorkflowAuthoringRequest } from '../workflowAuthoringRun';

type OnEvent = (event: WorkflowInputStreamEvent) => void;

function session(status: string, id = 's-1'): WorkflowInputSession {
  return { session_id: id, status } as WorkflowInputSession;
}

function handlers(overrides: Partial<WorkflowAuthoringHandlers> = {}): WorkflowAuthoringHandlers {
  return {
    isCurrent: () => true,
    isStopRequested: () => false,
    onStarted: vi.fn(),
    onProgress: vi.fn(),
    onPreview: vi.fn(),
    onStreamSettled: vi.fn(),
    onPending: vi.fn(),
    ...overrides
  };
}

function request(overrides: Partial<WorkflowAuthoringRequest> = {}): WorkflowAuthoringRequest {
  return { instruction: 'Daily news', idempotencyKey: 'key-1', signal: new AbortController().signal, ...overrides };
}

beforeEach(() => {
  service.streamWorkflowInstruction.mockReset();
  service.getWorkflowInstruction.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('runWorkflowAuthoring', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('forwards stream events and passes draftOnly as the stream options', async () => {
    service.streamWorkflowInstruction.mockImplementation(async (_t: string, _w: string | undefined, onEvent: OnEvent) => {
      onEvent({ type: 'started', session_id: 's-1', status: 'running' });
      onEvent({ type: 'progress', phase: 'planning' });
      onEvent({ type: 'preview', provisional: true, validated: true, workflow_index: 0, metadata: { title: 'Draft' }, graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] } } as unknown as WorkflowInputStreamEvent);
      return session('draft');
    });
    const h = handlers();
    const result = await runWorkflowAuthoring(request({ draftOnly: true, workflowId: 'wf-1' }), h);
    expect(result?.status).toBe('draft');
    expect(service.streamWorkflowInstruction).toHaveBeenCalledWith('Daily news', 'wf-1', expect.any(Function), expect.any(AbortSignal), 'key-1', { draftOnly: true });
    expect(h.onStarted).toHaveBeenCalledWith('s-1');
    expect(h.onProgress).toHaveBeenCalledTimes(1);
    expect(h.onPreview).toHaveBeenCalledTimes(1);
    expect(h.onStreamSettled).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('passes the source chat and turn of a chat Recommendation as stream options', async () => {
    service.streamWorkflowInstruction.mockResolvedValue(session('draft'));
    await runWorkflowAuthoring(request({ draftOnly: true, sourceChatId: 'chat-1', sourceMessageId: 'chat-1-turn' }), handlers());
    expect(service.streamWorkflowInstruction.mock.calls[0][5]).toEqual({
      draftOnly: true, sourceChatId: 'chat-1', sourceMessageId: 'chat-1-turn',
    });
    // A turn id never travels without its chat.
    await runWorkflowAuthoring(request({ draftOnly: true, sourceMessageId: 'orphan-turn' }), handlers());
    expect(service.streamWorkflowInstruction.mock.calls[1][5]).toEqual({ draftOnly: true });
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('keeps the stream call unchanged without draftOnly', async () => {
    service.streamWorkflowInstruction.mockResolvedValue(session('executed'));
    await runWorkflowAuthoring(request(), handlers());
    expect(service.streamWorkflowInstruction.mock.calls[0][5]).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('retries once with the same key when the stream fails before starting', async () => {
    service.streamWorkflowInstruction.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(session('draft'));
    const result = await runWorkflowAuthoring(request(), handlers());
    expect(result?.status).toBe('draft');
    expect(service.streamWorkflowInstruction).toHaveBeenCalledTimes(2);
    expect(service.streamWorkflowInstruction.mock.calls[1][4]).toBe('key-1');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('recovers the started session after a stopped stream', async () => {
    const controller = new AbortController();
    service.streamWorkflowInstruction.mockImplementation(async (_t: string, _w: string | undefined, onEvent: OnEvent) => {
      onEvent({ type: 'started', session_id: 's-9', status: 'running' });
      controller.abort();
      throw new DOMException('aborted', 'AbortError');
    });
    service.getWorkflowInstruction.mockResolvedValue(session('draft', 's-9'));
    const result = await runWorkflowAuthoring(request({ signal: controller.signal }), handlers({ isStopRequested: () => true }));
    expect(service.getWorkflowInstruction).toHaveBeenCalledWith('s-9');
    expect(result?.session_id).toBe('s-9');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('rethrows an abort that was not a stop request', async () => {
    const controller = new AbortController();
    controller.abort();
    service.streamWorkflowInstruction.mockRejectedValue(new DOMException('aborted', 'AbortError'));
    await expect(runWorkflowAuthoring(request({ signal: controller.signal }), handlers())).rejects.toThrow('aborted');
    expect(service.streamWorkflowInstruction).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('polls a queued session until it settles', async () => {
    vi.useFakeTimers();
    service.streamWorkflowInstruction.mockResolvedValue(session('queued'));
    service.getWorkflowInstruction.mockResolvedValueOnce(session('saving')).mockResolvedValueOnce(session('draft'));
    const h = handlers();
    const run = runWorkflowAuthoring(request(), h);
    await vi.runAllTimersAsync();
    const result = await run;
    expect(result?.status).toBe('draft');
    expect(h.onPending).toHaveBeenCalledTimes(2);
    expect(service.getWorkflowInstruction).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('returns null once the caller is no longer current', async () => {
    let current = true;
    service.streamWorkflowInstruction.mockImplementation(async () => {
      current = false;
      return session('draft');
    });
    const h = handlers({ isCurrent: () => current });
    expect(await runWorkflowAuthoring(request(), h)).toBeNull();
    expect(h.onStreamSettled).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview,app-memories.suggestions.post-processor
  it('resumes an existing session without streaming', async () => {
    service.getWorkflowInstruction.mockResolvedValue(session('executed', 's-2'));
    const h = handlers();
    const result = await runWorkflowAuthoring(request({ existingSessionId: 's-2' }), h);
    expect(result?.session_id).toBe('s-2');
    expect(service.streamWorkflowInstruction).not.toHaveBeenCalled();
    expect(h.onStreamSettled).not.toHaveBeenCalled();
  });
});
