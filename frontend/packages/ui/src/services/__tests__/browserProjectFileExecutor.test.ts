import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  activeFocus: vi.fn(),
  approveWrite: vi.fn(),
  getProject: vi.fn(),
  getContents: vi.fn(),
  getSettings: vi.fn(),
  listSources: vi.fn(),
  readHead: vi.fn(),
  receipt: vi.fn(),
  remote: vi.fn(),
  chatKey: new Uint8Array(32).fill(8),
}));

vi.mock("../../stores/userProfile", () => ({
  userProfile: {
    subscribe(run: (value: { user_id: string }) => void) {
      run({ user_id: "user-1" });
      return () => undefined;
    },
  },
}));
vi.mock("../../stores/projectFileApprovalStore", () => ({
  requestProjectWriteApproval: vi.fn(async () => true),
  requestProjectIgnoredReadApproval: vi.fn(async () => true),
  recordProjectFileChange: vi.fn(),
}));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: { getKey: vi.fn(async () => mocks.chatKey) },
}));
vi.mock("../cryptoService", () => ({
  decryptWithEmbedKey: vi.fn(async (value: string) => value),
  encryptWithEmbedKey: vi.fn(async () => "ciphertext"),
  wrapEmbedKeyWithChatKey: vi.fn(async () => "wrapped"),
}));
vi.mock("../projectService", () => ({
  approveProjectWrite: mocks.approveWrite,
  getActiveProjectFocus: mocks.activeFocus,
  getProject: mocks.getProject,
  getProjectContents: mocks.getContents,
  getProjectFileRevisionReceipt: mocks.receipt,
  getProjectSettings: mocks.getSettings,
  listProjectSources: mocks.listSources,
  readEncryptedProjectFile: mocks.readHead,
  requestProjectRemoteAccess: mocks.remote,
}));

import { createBrowserProjectFileExecutor } from "../browserProjectFileExecutor";
import type { ProjectFileJob } from "../projectFileJobExecutor";

const projectKey = new Uint8Array(32).fill(7);
const project = {
  project_id: "project-1",
  name: "Project",
  description: "",
  projectKey,
  encrypted: {},
};

function job(sourceId?: string): ProjectFileJob {
  return {
    protocol_version: 1,
    operation_id: "operation-1",
    chat_id: "chat-1",
    project_id: "project-1",
    ...(sourceId ? { source_id: sourceId } : {}),
    operation: "list",
    arguments: { path: "." },
    lease_token: "lease-token-long-enough",
    lease_generation: 1,
    lease_expires_at: Math.floor(Date.now() / 1000) + 60,
  };
}

describe("browser Project file executor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.activeFocus.mockResolvedValue({
      active: true,
      project_id: "project-1",
      focus_id: "focus-1",
      team_id: "team-1",
      activated_at: 1,
    });
    mocks.getProject.mockResolvedValue(project);
    mocks.getSettings.mockResolvedValue({
      writeMode: "apply_and_show",
      selectionRequired: false,
      settings: {},
      encrypted: { encrypted_settings: null },
    });
    mocks.getContents.mockResolvedValue({ folders: [], items: [] });
    mocks.listSources.mockResolvedValue([]);
    mocks.receipt.mockResolvedValue(null);
  });

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit,projects.files.private-path-deny
  it("routes a hosted job locally and taints every alias of protected metadata before reading a head", async () => {
    mocks.getContents.mockResolvedValue({
      folders: [],
      items: [
        { item_type: "embed", target_id: "private-head", displayName: ".env", metadata: { path: ".env" }, encrypted: {} },
        { item_type: "embed", target_id: "private-head", displayName: "alias.ts", metadata: { path: "src/alias.ts" }, encrypted: {} },
        { item_type: "embed", target_id: "allowed-head", displayName: "allowed.ts", metadata: { path: "src/allowed.ts" }, encrypted: {} },
      ],
    });
    const send = vi.fn(async () => undefined);
    const executor = createBrowserProjectFileExecutor({
      transport: { send, commit: vi.fn() },
      isActiveChat: (chatId) => chatId === "chat-1",
    });

    await executor.request(job());

    expect(mocks.remote).not.toHaveBeenCalled();
    expect(mocks.readHead).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledWith("project_file_operation_result", expect.objectContaining({
      status: "completed",
      result: { entries: [{ path: "src/allowed.ts", kind: "file" }], truncated: false },
    }));
  });

  // contract-test: direct surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.chat-focus-required
  it("routes a selected remote source with fresh focus, Team context, and no plaintext persistence", async () => {
    const source = { source_id: "source-1", status: "connected" };
    mocks.listSources.mockResolvedValue([source]);
    mocks.remote.mockResolvedValue({ entries: [{ path: "src", kind: "directory" }] });
    const send = vi.fn(async () => undefined);
    const executor = createBrowserProjectFileExecutor({
      transport: { send, commit: vi.fn() },
      isActiveChat: (chatId) => chatId === "chat-1",
    });

    await executor.request(job("source-1"));

    expect(mocks.activeFocus).toHaveBeenCalledTimes(2);
    expect(mocks.getProject).toHaveBeenCalledWith("project-1", { teamId: "team-1" });
    expect(mocks.getSettings).toHaveBeenCalledWith(project, { teamId: "team-1" });
    expect(mocks.listSources).toHaveBeenCalledWith(project, { teamId: "team-1" });
    expect(mocks.getContents).toHaveBeenCalledWith(project, { teamId: "team-1" });
    expect(mocks.remote).toHaveBeenCalledWith(
      project,
      source,
      { ownerId: "user-1", teamId: "team-1" },
      "list",
      { path: "." },
      undefined,
      undefined,
    );
    expect(send).toHaveBeenCalledWith("project_file_operation_result", expect.objectContaining({
      status: "completed",
      result: { entries: [{ path: "src", kind: "directory" }] },
    }));
  });

  // contract-test: direct surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.chat-focus-required
  it("routes an omitted source to the sole remote source but rejects ambiguous sources", async () => {
    const source = { source_id: "source-1", status: "connected" };
    mocks.listSources.mockResolvedValue([source]);
    mocks.remote.mockResolvedValue({ entries: [] });
    const send = vi.fn(async () => undefined);
    const executor = createBrowserProjectFileExecutor({
      transport: { send, commit: vi.fn() },
      isActiveChat: (chatId) => chatId === "chat-1",
    });

    await executor.request(job());
    expect(mocks.remote).toHaveBeenCalledWith(
      project, source, { ownerId: "user-1", teamId: "team-1" },
      "list", { path: "." }, undefined, undefined,
    );

    mocks.listSources.mockResolvedValue([source, { source_id: "source-2", status: "connected" }]);
    await executor.request({ ...job(), operation_id: "operation-2" });
    expect(send).toHaveBeenLastCalledWith("project_file_operation_result", expect.objectContaining({
      status: "failed",
      result: { code: "source_selection_required" },
    }));
  });
});
