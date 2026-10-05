import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  addExistingTargetToProject: vi.fn(),
  getProject: vi.fn(),
  createUserPlan: vi.fn(),
  listProjectSources: vi.fn(async () => []),
  getProjectContents: vi.fn(async () => ({ items: [], folders: [] })),
  updateProjectItemMetadata: vi.fn(),
  workflowApiRequest: vi.fn(),
  getActiveProjectFocus: vi.fn(),
  requestProjectRemoteAccess: vi.fn(),
  getProjectSettings: vi.fn(),
  approveProjectWrite: vi.fn(),
  activeChatGet: vi.fn(() => null),
  pendingMentionValue: null as unknown,
}));

vi.mock("../projectService", () => ({
  addExistingTargetToProject: mocks.addExistingTargetToProject,
  getProject: mocks.getProject,
  listProjectSources: mocks.listProjectSources,
  getProjectContents: mocks.getProjectContents,
  updateProjectItemMetadata: mocks.updateProjectItemMetadata,
  getActiveProjectFocus: mocks.getActiveProjectFocus,
  requestProjectRemoteAccess: mocks.requestProjectRemoteAccess,
  getProjectSettings: mocks.getProjectSettings,
  approveProjectWrite: mocks.approveProjectWrite,
}));
vi.mock('../../stores/workflowWorkspaceStore', () => ({ workflowApiRequest: mocks.workflowApiRequest }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner' }) }));
vi.mock('../../stores/projectFileApprovalStore', () => ({ requestProjectWriteApproval: vi.fn(async () => false), recordProjectFileChange: vi.fn() }));
vi.mock('../../i18n/translations', async () => ({ text: (await import('svelte/store')).writable((key: string) => key) }));

vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: { clearActiveChat: vi.fn(), get: mocks.activeChatGet },
}));

vi.mock("../../stores/pendingMentionStore", () => {
  return {
    pendingMentionStore: {
      subscribe: vi.fn(),
      set: (value: unknown) => {
        mocks.pendingMentionValue = value;
      },
    },
  };
});

vi.mock("../../stores/phasedSyncStateStore", () => ({
  NEW_CHAT_SENTINEL: "__new_chat__",
  phasedSyncState: {
    setCurrentActiveChatId: vi.fn(),
    markUserMadeExplicitChoice: vi.fn(),
  },
}));

vi.mock("../chatSyncService", () => ({
  chatSyncService: { sendSetActiveChat: vi.fn(async () => undefined) },
}));

vi.mock("../userPlanService", () => ({
  createUserPlan: mocks.createUserPlan,
}));

import {
  consumeProjectWorkflowTarget,
  createPlanForProjectTarget,
  prepareProjectChatNavigation,
  prepareProjectWorkflowNavigation,
  projectWorkflowAssociationWarning,
  saveWorkflowToProjectTarget,
  WorkflowRemoteFilePendingError,
} from "../projectCreationNavigation";

describe("project creation navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.pendingMentionValue = null;
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required
  it("opens a new chat with the selected Project folder mention activated", () => {
    prepareProjectChatNavigation({
      projectId: "project-1",
      projectName: "Launch",
      folderId: "folder-2",
      folderPath: "Planning/Q4",
    });

    expect(mocks.pendingMentionValue).toMatchObject({
      syntax: "@project-folder:project-1:Planning%2FQ4:read",
      type: "project_folder",
      displayName: "Launch-Q4",
      projectId: "project-1",
      projectPath: "Planning/Q4",
      projectAccessMode: "read",
    });
  });

  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it("consumes a pending workflow target exactly once", () => {
    const target = {
      projectId: "project-1",
      projectName: "Launch",
      folderId: "folder-2",
      folderPath: "Planning/Q4",
    };

    prepareProjectWorkflowNavigation(target);

    expect(consumeProjectWorkflowTarget()).toEqual(target);
    expect(consumeProjectWorkflowTarget()).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it("reports a failed Project association without losing the created workflow outcome", () => {
    expect(
      projectWorkflowAssociationWarning(
        {
          projectId: "project-1",
          projectName: "Launch",
          folderId: "folder-2",
          folderPath: "Planning/Q4",
        },
        new Error("Project service unavailable"),
      ),
    ).toBe(
      "Workflow created, but it could not be added to Launch / Planning/Q4. Project service unavailable",
    );
  });

  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it("creates a draft Plan linked to the selected Project through the Plan service", async () => {
    const createdPlan = { plan_id: "plan-2", linkedProjectIds: ["project-1"] };
    mocks.createUserPlan.mockResolvedValue(createdPlan);

    await expect(
      createPlanForProjectTarget({
        projectId: "project-1",
        projectName: "Launch",
        folderId: "folder-2",
        folderPath: "Planning/Q4",
      }),
    ).resolves.toBe(createdPlan);

    expect(mocks.createUserPlan).toHaveBeenCalledWith({
      title: "Untitled plan",
      goal: "Plan work for Launch",
      status: "draft",
      linkedProjectIds: ["project-1"],
    });
  });

  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it("persists a created workflow in the selected encrypted Project folder", async () => {
    const project = { project_id: "project-1", projectKey: new Uint8Array(32) };
    mocks.getProject.mockResolvedValue(project);
    mocks.addExistingTargetToProject.mockResolvedValue(undefined);

    await saveWorkflowToProjectTarget(
      {
        projectId: "project-1",
        projectName: "Launch",
        folderId: "folder-2",
        folderPath: "Planning/Q4",
        teamId: "team-4",
      },
      "workflow-3",
      "Weekly review",
    );

    expect(mocks.getProject).toHaveBeenCalledWith("project-1", {
      teamId: "team-4",
    });
    expect(mocks.addExistingTargetToProject).toHaveBeenCalledWith(
      project,
      "workflow-3",
      "workflow",
      "Weekly review",
      "folder-2",
      {
        source: "workflow_target",
        path: "Planning/Q4",
        source_id: undefined,
      },
      { teamId: "team-4" },
    );
  });

  // contract-test: supporting surface=gui.web assertions=workflows.portability.remote-project-save
  it('retains one encrypted association and shows pending when its remote source cannot write', async () => {
    const project = { project_id: 'project-1', projectKey: new Uint8Array(32) };
    mocks.getProject.mockResolvedValue(project);
    mocks.listProjectSources.mockResolvedValue([{ source_id: 'remote-1', source_type: 'remote_folder', sourceSessionId: null }] as never);
    mocks.workflowApiRequest.mockResolvedValue({ workflow: { id: 'workflow-3', current_version_id: 'v1' } });
    await expect(saveWorkflowToProjectTarget({ projectId: 'project-1', projectName: 'Launch', sourceId: 'remote-1', folderPath: 'automation' },
      'workflow-3', 'Review')).rejects.toBeInstanceOf(WorkflowRemoteFilePendingError);
    expect(mocks.addExistingTargetToProject).toHaveBeenCalledWith(project, 'workflow-3', 'workflow', 'Review', undefined,
      expect.objectContaining({ remote_file_status: 'pending', remote_workflow_file: {
        project_id: 'project-1', source_id: 'remote-1', folder_path: 'automation',
      } }), { teamId: null });
    expect(mocks.requestProjectRemoteAccess).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=workflows.portability.remote-project-save
  it('retries the previously bound source when other remote sources are available', async () => {
    const project = { project_id: 'project-1', projectKey: new Uint8Array(32) };
    const binding = { project_id: 'project-1', source_id: 'remote-1', folder_path: 'automation' };
    mocks.getProject.mockResolvedValue(project);
    mocks.listProjectSources.mockResolvedValue([
      { source_id: 'remote-1', source_type: 'remote_folder', status: 'offline' },
      { source_id: 'remote-2', source_type: 'remote_folder', status: 'online' },
    ] as never);
    mocks.getProjectContents.mockResolvedValue({ folders: [], items: [{ project_item_id: 'item-1',
      item_type: 'workflow', target_id: 'workflow-3', metadata: { remote_workflow_file: binding } }] } as never);
    mocks.workflowApiRequest.mockResolvedValue({ workflow: { id: 'workflow-3', current_version_id: 'v1' } });
    await expect(saveWorkflowToProjectTarget({ projectId: 'project-1', projectName: 'Launch' },
      'workflow-3', 'Review')).rejects.toBeInstanceOf(WorkflowRemoteFilePendingError);
    expect(mocks.updateProjectItemMetadata).toHaveBeenCalledWith(project, 'item-1',
      expect.objectContaining({ remote_file_error: 'source_offline', remote_workflow_file: binding }), { teamId: null });
    expect(mocks.addExistingTargetToProject).not.toHaveBeenCalled();
  });

});
