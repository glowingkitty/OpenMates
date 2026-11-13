// Pure draft helpers of the chat workflow side panel.
import { describe, expect, it } from 'vitest';
import type { WorkflowDetail, WorkflowGraph } from '../../../stores/workflowWorkspaceStore';
import type { WorkflowAcceptedPreview, WorkflowInputSession } from '../../../services/workflowInputService';
import type { WorkflowSidePanelRequest } from '../../../stores/workflowSidePanelStore';
import { draftFromSession, draftFromWorkflow, previewFromStreamEvent, saveTarget, shouldStartAuthoring } from '../workflowChatDraft';

const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: 'schedule',
  nodes: [{ id: 'schedule', type: 'schedule_trigger', config: { schedule: { type: 'daily', time: '09:00' } } }],
  edges: []
};

const saved = {
  id: 'wf-1', title: 'Saved', description: 'Old', category: 'news', icon: 'news',
  status: 'active', enabled: true, current_version_id: 'v1', graph
} as WorkflowDetail;

function request(overrides: Partial<WorkflowSidePanelRequest> = {}): WorkflowSidePanelRequest {
  return { chatId: 'chat-1', recommendationId: 'rec-1', mode: 'create', workflowId: null, instruction: 'Daily news', ...overrides };
}

function session(overrides: Partial<WorkflowInputSession>): WorkflowInputSession {
  return { session_id: 's-1', status: 'draft', ...overrides } as WorkflowInputSession;
}

describe('shouldStartAuthoring', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('starts only for a non-empty instruction', () => {
    expect(shouldStartAuthoring(request())).toBe(true);
    expect(shouldStartAuthoring(request({ mode: 'update', workflowId: 'wf-1', instruction: '' }))).toBe(false);
    expect(shouldStartAuthoring(request({ instruction: '   ' }))).toBe(false);
  });
});

describe('saveTarget', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('creates a new workflow for an unsaved create draft', () => {
    expect(saveTarget(request(), null)).toEqual({ action: 'created', workflowId: null });
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('patches the requested workflow in update mode', () => {
    expect(saveTarget(request({ mode: 'update', workflowId: 'wf-1' }), null)).toEqual({ action: 'updated', workflowId: 'wf-1' });
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('patches the workflow created by an earlier save without changing the action', () => {
    expect(saveTarget(request(), 'wf-new')).toEqual({ action: 'created', workflowId: 'wf-new' });
  });
});

describe('draftFromSession', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('accepts a draft session with a v2 preview workflow', () => {
    const result = draftFromSession(session({ preview_workflow: { ...saved, id: 'preview', title: 'New title', graph }, assumptions: ['Berlin'] }), null);
    expect(result).toMatchObject({ kind: 'draft', assumptions: ['Berlin'], draft: { title: 'New title', category: 'news' } });
    if (result.kind === 'draft') expect(result.draft.graph).not.toBe(graph);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('falls back to the base workflow metadata', () => {
    const result = draftFromSession(session({ preview_workflow: { ...saved, title: '', description: null, category: undefined, icon: undefined } }), saved);
    expect(result).toMatchObject({ kind: 'draft', draft: { title: 'Saved', description: 'Old', category: 'news', icon: 'news' } });
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('rejects persisted, clarification and graph-less sessions', () => {
    expect(draftFromSession(session({ status: 'executed', message: 'Saved' }), null)).toEqual({ kind: 'error', message: 'Saved' });
    expect(draftFromSession(session({ status: 'needs_clarification', message: 'Which city?' }), null)).toEqual({ kind: 'error', message: 'Which city?' });
    expect(draftFromSession(session({ preview_workflow: null }), null)).toEqual({ kind: 'error', message: null });
  });
});

describe('draftFromWorkflow / previewFromStreamEvent', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('copies a saved workflow into an independent draft', () => {
    const draft = draftFromWorkflow(saved);
    expect(draft).toMatchObject({ title: 'Saved', description: 'Old', category: 'news', icon: 'news' });
    expect(draft.graph).toEqual(graph);
    expect(draft.graph).not.toBe(graph);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('keeps the base id for update previews and a provisional id for new ones', () => {
    const event = { type: 'preview', provisional: true, validated: true, workflow_index: 0, metadata: { title: 'Draft' }, graph } as unknown as WorkflowAcceptedPreview;
    expect(previewFromStreamEvent(event, saved)).toMatchObject({ id: 'wf-1', title: 'Draft', status: 'provisional', category: 'news' });
    expect(previewFromStreamEvent(event, null).id).toBe('provisional-0');
  });
});
