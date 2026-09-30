import { describe, expect, it, vi } from 'vitest';

const { apiFetch, apiRequest } = vi.hoisted(() => ({ apiFetch: vi.fn(), apiRequest: vi.fn() }));
vi.mock('../../stores/workflowWorkspaceStore', () => ({ workflowApiFetch: apiFetch, workflowApiRequest: apiRequest }));

import { committedWorkflows, getWorkflowInstruction, stopWorkflowInstruction, streamWorkflowInstruction, type WorkflowInputSession } from '../workflowInputService';

function fragmentedResponse(parts: string[]): Response {
  const encoder = new TextEncoder();
  return { body: new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    }
  }) } as Response;
}

describe('workflow input stream', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview
  it('parses fragmented SSE and returns only the final session', async () => {
    const graph = { version: 2, trigger_node_id: 'manual', nodes: [{ id: 'manual', type: 'manual_trigger' }], edges: [] };
    const preview = { type: 'preview', workflow_index: 0, graph, metadata: { title: 'Morning report' }, accepted_node_count: 1, node: graph.nodes[0], provisional: true, validated: true };
    const final = { type: 'session', session: { session_id: 'session-1', status: 'executed', workflows: [] } };
    apiFetch.mockResolvedValueOnce(fragmentedResponse([
      'data: {"type":"progress","phase":"planning"}\n\n',
      `data: ${JSON.stringify(preview).slice(0, 30)}`,
      `${JSON.stringify(preview).slice(30)}\r\n\r\ndata: ${JSON.stringify(final)}\n`,
      '\n'
    ]));
    const events: unknown[] = [];
    const session = await streamWorkflowInstruction('Make a morning report', undefined, event => events.push(event));
    expect(events).toEqual([{ type: 'progress', phase: 'planning' }, preview, final]);
    expect(session.status).toBe('executed');
    expect(apiFetch).toHaveBeenCalledWith('/v1/workflows/input/stream', expect.objectContaining({
      method: 'POST', body: expect.stringContaining('Make a morning report')
    }), 'text/event-stream', undefined);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.edit-control-and-undo
  it('rejects a stream that closes without a final session', async () => {
    apiFetch.mockResolvedValueOnce(fragmentedResponse(['data: {"type":"progress","phase":"saving"}\n\n']));
    await expect(streamWorkflowInstruction('Incomplete', undefined, () => undefined)).rejects.toThrow('before a result');
  });

  // contract-test: supporting surface=gui.web assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
  it('sends one idempotency key and exposes the durable session before planning', async () => {
    const started = { type: 'started', session_id: 'durable-1', status: 'running' };
    apiFetch.mockResolvedValueOnce(fragmentedResponse([
      `data: ${JSON.stringify(started)}\n\n`,
      'data: {"type":"session","session":{"session_id":"durable-1","status":"needs_clarification"}}\n\n'
    ]));
    const events: unknown[] = [];
    await streamWorkflowInstruction('Create a report', undefined, event => events.push(event), undefined, '7e6a620a-f09f-4aa9-b87a-79ad9b03d32d');
    expect(events[0]).toEqual(started);
    expect(JSON.parse(apiFetch.mock.lastCall?.[1].body)).toMatchObject({ idempotency_key: '7e6a620a-f09f-4aa9-b87a-79ad9b03d32d' });
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.edit-control-and-undo
  it('normalizes backend change identifiers for the editor review', async () => {
    apiRequest.mockResolvedValueOnce({ session: {
      session_id: 'session-2', status: 'executed',
      changes: [{ workflow_id: 'workflow-1', operation: 'update', added_node_ids: ['new'], changed_node_ids: ['kept'], removed_node_ids: ['old'] }],
      mutations: [{ target_id: 'workflow-1', type: 'update_workflow', before: { graph: { nodes: [{ id: 'old', type: 'send_chat_message', title: 'Old message' }] } } }]
    } });
    const session = await getWorkflowInstruction('session-2');
    expect(session.changes?.[0]).toMatchObject({
      added_node_ids: ['new'], edited_node_ids: ['kept'], removed_nodes: [{ id: 'old', title: 'Old message' }]
    });
  });

  // contract-test: supporting surface=gui.web assertions=workflows.authoring.provisional-validation
  it('acknowledges Stop on the server and recognizes a persisted partial draft', async () => {
    apiRequest.mockResolvedValueOnce({ session: { session_id: 'session-stop', status: 'running', stop_requested: true } });
    const acknowledgment = await stopWorkflowInstruction('session-stop');
    expect(acknowledgment.stop_requested).toBe(true);
    expect(apiRequest).toHaveBeenLastCalledWith('/v1/workflows/input/session-stop/stop', { method: 'POST', body: '{}' });
    const partial = { session_id: 'session-stop', status: 'draft', partial_reason: 'stopped', workflows: [{ id: 'workflow-1' }] } as WorkflowInputSession;
    expect(committedWorkflows(partial)).toEqual([{ id: 'workflow-1' }]);
  });
});
