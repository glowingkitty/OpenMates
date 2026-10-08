import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { workflowWorkspaceStore, type WorkflowDetail } from '../workflowWorkspaceStore';
import { activeTeamContext, setActiveTeamContext } from '../teamStore';

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

const json = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const detail = { id: 'workflow-1', title: 'Morning update', graph: { nodes: [], edges: [] } } as unknown as WorkflowDetail;

describe('workflowWorkspaceStore navigation cache', () => {
  beforeEach(() => {
    activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    workflowWorkspaceStore.reset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    workflowWorkspaceStore.reset();
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it('loads and creates workflows in the selected Team, discarding a Personal response after a switch', async () => {
    const oldList = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => oldList.promise)
      .mockResolvedValue(json({ workflows: [{ ...detail, id: 'team-workflow' }] }));
    const personalLoad = workflowWorkspaceStore.loadWorkflows();
    setActiveTeamContext({ team_id: 'team-a' } as Parameters<typeof setActiveTeamContext>[0]);
    const teamLoad = workflowWorkspaceStore.loadWorkflows();
    oldList.resolve(json({ workflows: [detail] }));
    await expect(personalLoad).rejects.toThrow('Workflow context changed');
    await teamLoad;
    expect(get(workflowWorkspaceStore).workflows.map(item => item.id)).toEqual(['team-workflow']);
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.test/v1/workflows');
    expect(fetchMock.mock.calls[1][0]).toBe('https://api.test/v1/workflows?team_id=team-a');

    fetchMock.mockResolvedValue(json({ workflow: { ...detail, id: 'created-team-workflow' } }));
    await workflowWorkspaceStore.createWorkflow({ title: 'Team', graph: detail.graph,
      enabled: false, runContentRetention: 'last_5', teamId: 'team-a' });
    expect(JSON.parse(fetchMock.mock.lastCall?.[1]?.body as string).team_id).toBe('team-a');
    await expect(workflowWorkspaceStore.createWorkflow({ title: 'Wrong project', graph: detail.graph,
      enabled: false, runContentRetention: 'last_5', teamId: 'team-b' }))
      .rejects.toThrow('another workspace');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.website-change.composition
  it('preserves a starter description and keeps creation disabled', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ workflow: detail }));
    await workflowWorkspaceStore.createWorkflow({
      title: 'Website changes', description: 'The first read initializes without a message.',
      graph: detail.graph, enabled: false, runContentRetention: 'last_5',
    });
    const request = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(request.description).toBe('The first read initializes without a message.');
    expect(request.enabled).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.chat-owned,workflows.chat.embedded-lifecycle
  it('keeps a chat-owned detail out of the reusable list and saves a disabled copy', async () => {
    const chatWorkflow = { ...detail, id: 'chat-workflow', lifecycle: 'chat_embed', enabled: false } as WorkflowDetail;
    workflowWorkspaceStore.upsertWorkflow(chatWorkflow);
    expect(get(workflowWorkspaceStore).workflows).toEqual([]);
    const copy = { ...detail, id: 'saved-copy', lifecycle: 'persisted', enabled: false } as WorkflowDetail;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ workflow: copy }));
    await expect(workflowWorkspaceStore.saveAsReusableWorkflow(chatWorkflow.id, 'copy-once')).resolves.toMatchObject({ id: 'saved-copy', enabled: false });
    expect(get(workflowWorkspaceStore).workflows.map(item => item.id)).toEqual(['saved-copy']);
    expect(fetchMock.mock.calls[0][0]).toContain('/v1/workflows/chat-workflow/save-as-reusable');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ idempotency_key: 'copy-once' });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.chat-owned,workflows.chat.embedded-lifecycle
  it('filters chat-owned list rows while retaining an explicitly opened detail', async () => {
    const chatWorkflow = { ...detail, id: 'chat-workflow', lifecycle: 'chat_embed', enabled: false } as WorkflowDetail;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).endsWith('/runs') ? json({ runs: [] }) : json({ workflows: [chatWorkflow] }));
    workflowWorkspaceStore.upsertWorkflow(chatWorkflow);
    await workflowWorkspaceStore.selectWorkflow(chatWorkflow.id);
    await workflowWorkspaceStore.loadWorkflows({ force: true });
    expect(get(workflowWorkspaceStore).workflows).toEqual([]);
    expect(get(workflowWorkspaceStore).selectedWorkflowId).toBe('chat-workflow');
  });

  // contract-test: direct surface=gui.web assertions=workflows.chat.invocation,workflows.chat.result-return
  it('passes chat destination overrides and requested return outputs to an existing run', async () => {
    const run = { id:'run-chat', workflow_id:'workflow-1', status:'queued' };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ run }));
    await workflowWorkspaceStore.runWorkflow('workflow-1', {
      sourceChatId:'chat-source', messageDestinationOverrides:{ send:'chat-source' },
      returnOutputs:{ summarize:{ brief:'answer' } }, idempotencyKey:'invoke-chat-once',
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toMatchObject({
      source_chat_id:'chat-source', message_destination_overrides:{ send:'chat-source' },
      return_outputs:{ summarize:{ brief:'answer' } },
    });
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe('invoke-chat-once');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition
  it('treats a loaded empty workflow list as fresh', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ workflows: [] }));
    await workflowWorkspaceStore.loadWorkflows();
    await workflowWorkspaceStore.loadWorkflows();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(get(workflowWorkspaceStore).listStatus).toBe('ready');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.detail.shared-template-runs-tabs
  it('keeps a deep link pending until the replacement list loads after reset', async () => {
    const oldList = deferred<Response>();
    const replacementList = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => oldList.promise)
      .mockImplementationOnce(() => replacementList.promise);

    const firstLoad = workflowWorkspaceStore.loadWorkflows();
    workflowWorkspaceStore.reset();
    const generationAfterReset = get(workflowWorkspaceStore).generation;
    const replacementLoad = workflowWorkspaceStore.loadWorkflows();
    const waitingForReplacement = get(workflowWorkspaceStore);
    expect(waitingForReplacement.listStatus).toBe('loading');

    oldList.resolve(json({ workflows: [] }));
    await firstLoad;
    expect(get(workflowWorkspaceStore)).toEqual(waitingForReplacement);
    expect(get(workflowWorkspaceStore).generation).toBe(generationAfterReset);
    expect(get(workflowWorkspaceStore).listStatus).not.toBe('ready');

    replacementList.resolve(json({ workflows: [detail] }));
    await replacementLoad;
    expect(get(workflowWorkspaceStore).listStatus).toBe('ready');
    expect(get(workflowWorkspaceStore).workflows[0]?.id).toBe(detail.id);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.detail.shared-template-runs-tabs,workflows-ui.runs.timeline-execution-detail
  it('publishes detail before run history finishes and reuses the cached empty history', async () => {
    const runs = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = String(input);
      return path.endsWith('/runs') ? runs.promise : Promise.resolve(json({ workflow: detail }));
    });

    await expect(workflowWorkspaceStore.selectWorkflow(detail.id)).resolves.toMatchObject({ id: detail.id });
    expect(get(workflowWorkspaceStore).selectedWorkflow?.id).toBe(detail.id);
    expect(get(workflowWorkspaceStore).runsStatus).toBe('loading');

    runs.resolve(json({ runs: [] }));
    await vi.waitFor(() => expect(get(workflowWorkspaceStore).runsStatus).toBe('ready'));
    await workflowWorkspaceStore.selectWorkflow(detail.id);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.template.explicit-guarded-save
  it('rejects a late detail response after a local workflow update', async () => {
    const oldDetail = deferred<Response>();
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => String(input).endsWith('/runs')
      ? Promise.resolve(json({ runs: [] }))
      : oldDetail.promise);
    const selection = workflowWorkspaceStore.selectWorkflow(detail.id);
    workflowWorkspaceStore.upsertWorkflow({ ...detail, title: 'Locally saved' });
    oldDetail.resolve(json({ workflow: detail }));
    await selection;
    expect(get(workflowWorkspaceStore).selectedWorkflow?.title).toBe('Locally saved');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
  it('ignores an old run-list failure after newer run detail succeeds', async () => {
    const oldRuns = deferred<Response>();
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = String(input);
      if (path.endsWith('/runs')) return oldRuns.promise;
      if (path.endsWith('/runs/run-1')) return Promise.resolve(json({ run: { id: 'run-1', status: 'completed' } }));
      return Promise.resolve(json({ workflow: detail }));
    });

    await workflowWorkspaceStore.selectWorkflow(detail.id);
    await workflowWorkspaceStore.getWorkflowRun(detail.id, 'run-1');
    expect(get(workflowWorkspaceStore).runsStatus).toBe('ready');

    oldRuns.resolve(new Response(JSON.stringify({ detail: 'Old read failed' }), { status: 500 }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const state = get(workflowWorkspaceStore);
    expect(state.runsStatus).toBe('ready');
    expect(state.error).toBeNull();
    expect(state.runsByWorkflowId[detail.id]?.[0]?.id).toBe('run-1');
  });
});
