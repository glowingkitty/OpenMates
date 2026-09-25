import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  addExistingTargetToProject: vi.fn(),
  getProject: vi.fn(),
  createUserPlan: vi.fn(),
  pendingMentionValue: null as unknown,
}));

vi.mock("../projectService", () => ({
  addExistingTargetToProject: mocks.addExistingTargetToProject,
  getProject: mocks.getProject,
}));

vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: { clearActiveChat: vi.fn() },
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
});
