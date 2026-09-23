import { describe, expect, it, vi } from "vitest";
import type {
  ActiveProjectFocus,
  ProjectSettingsViewModel,
  ProjectViewModel,
} from "../projectService";
import {
  activateProjectFocusForSend,
  deactivateFocusForChat,
  extractProjectFocusSendIntent,
  isProjectFocusId,
  ProjectFocusSendPreflightError,
} from "../projectFocusSendPreflight";

function project(projectId: string): ProjectViewModel {
  return {
    project_id: projectId,
    name: "Project",
    description: "",
    projectKey: new Uint8Array(32),
    encrypted: {
      project_id: projectId,
      encrypted_project_key: "wrapped",
      encrypted_name: "name",
      created_at: 1,
      updated_at: 1,
      last_opened_at: 1,
    },
  };
}

function settings(focusId: string, instructions: string): ProjectSettingsViewModel {
  return {
    writeMode: "apply_and_show",
    selectionRequired: false,
    settings: {
      default_focus: {
        focus_id: focusId,
        name: "Work on Project",
        instructions,
        source: "generated",
      },
    },
    encrypted: {},
  };
}

describe("Project focus send preflight", () => {
  // contract-test: direct surface=gui.web assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
  it("captures current structured Project mention consent without trusting plaintext syntax", () => {
    expect(extractProjectFocusSendIntent({
      type: "doc",
      content: [
        { type: "text", text: "historical @project:forged:read" },
        {
          type: "paragraph",
          content: [{
            type: "genericMention",
            attrs: { mentionType: "project_file", projectId: "project-1" },
          }],
        },
      ],
    })).toEqual({ projectId: "project-1", source: "composer_project_mention" });

    expect(extractProjectFocusSendIntent({
      type: "doc",
      content: [{ type: "text", text: "@project:project-1:read_write" }],
    })).toBeNull();
  });

  // contract-test: direct surface=gui.web assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
  it("rejects one send that ambiguously selects distinct Projects", () => {
    try {
      extractProjectFocusSendIntent({
        type: "doc",
        content: [
          { type: "genericMention", attrs: { mentionType: "project", projectId: "project-1" } },
          { type: "genericMention", attrs: { mentionType: "project_folder", projectId: "project-2" } },
        ],
      });
      throw new Error("Expected multiple Project mentions to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ProjectFocusSendPreflightError);
      expect((error as ProjectFocusSendPreflightError).code).toBe("MULTIPLE_PROJECTS");
    }
  });

  // contract-test: direct surface=gui.web assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
  it("activates the exact persisted chat and returns its durable Project pill identity", async () => {
    const focusId = "0f82c8d1-9a8d-4f02-97cf-53ef54e5bdf1";
    const activate = vi.fn(async (): Promise<ActiveProjectFocus> => ({
      active: true,
      project_id: "project-2",
      focus_id: focusId,
      team_id: "team-1",
      activated_at: 10,
    }));
    const selectedProject = project("project-2");
    const getSelectedProject = vi.fn(async () => selectedProject);
    const getSelectedSettings = vi.fn(async () => settings(focusId, "Current instruction"));

    await expect(activateProjectFocusForSend(
      { projectId: "project-2", source: "composer_project_mention" },
      { chatId: "chat-1", preflightId: "preflight-1", teamId: "team-1" },
      {
        getProject: getSelectedProject,
        getProjectSettings: getSelectedSettings,
        activateProjectFocus: activate,
      },
    )).resolves.toEqual(expect.objectContaining({
      project_id: "project-2",
      focus_id: focusId,
      project_name: "Project",
    }));
    expect(isProjectFocusId(focusId)).toBe(true);
    expect(isProjectFocusId("jobs-career_insights")).toBe(false);

    expect(activate).toHaveBeenCalledWith(
      "project-2",
      {
        chat_id: "chat-1",
        focus_id: focusId,
        instruction: "Current instruction",
      },
      { teamId: "team-1" },
    );
    expect(getSelectedProject).toHaveBeenCalledWith("project-2", { teamId: "team-1" });
    expect(getSelectedSettings).toHaveBeenCalledWith(selectedProject, { teamId: "team-1" });
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required
  it("cannot activate before the durable chat preflight acknowledgement", async () => {
    const activate = vi.fn();
    await expect(activateProjectFocusForSend(
      { projectId: "project-1", source: "composer_project_mention" },
      { chatId: "chat-1", preflightId: "" },
      {
        getProject: vi.fn(async () => project("project-1")),
        getProjectSettings: vi.fn(async () => settings("focus-1", "Instruction")),
        activateProjectFocus: activate,
      },
    )).rejects.toMatchObject({ code: "CHAT_PREFLIGHT_REQUIRED" });
    expect(activate).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required
  it("fails closed when encrypted Project settings have no usable default focus", async () => {
    const activate = vi.fn();
    await expect(activateProjectFocusForSend(
      { projectId: "project-1", source: "composer_project_mention" },
      { chatId: "chat-1", preflightId: "preflight-1" },
      {
        getProject: vi.fn(async () => project("project-1")),
        getProjectSettings: vi.fn(async (): Promise<ProjectSettingsViewModel> => ({
          writeMode: "apply_and_show",
          selectionRequired: false,
          settings: {},
          encrypted: {},
        })),
        activateProjectFocus: activate,
      },
    )).rejects.toMatchObject({ code: "PROJECT_FOCUS_UNAVAILABLE" });
    expect(activate).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
  it("revokes Project authority before clearing the normal focus lifecycle", async () => {
    const calls: string[] = [];
    await deactivateFocusForChat(
      {
        chatId: "chat-1",
        focusId: "focus-1",
        sendCatalogDeactivation: vi.fn(async () => {
          calls.push("catalog");
        }),
      },
      {
        deactivateProjectFocus: vi.fn(async () => {
          calls.push("project");
        }),
      },
    );
    expect(calls).toEqual(["project", "catalog"]);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required
  it("does not show focus as off when Project authority revocation fails", async () => {
    const sendCatalogDeactivation = vi.fn();
    await expect(deactivateFocusForChat(
      {
        chatId: "chat-1",
        focusId: "focus-1",
        sendCatalogDeactivation,
      },
      {
        deactivateProjectFocus: vi.fn(async () => {
          throw new Error("offline");
        }),
      },
    )).rejects.toThrow("offline");
    expect(sendCatalogDeactivation).not.toHaveBeenCalled();
  });
});
