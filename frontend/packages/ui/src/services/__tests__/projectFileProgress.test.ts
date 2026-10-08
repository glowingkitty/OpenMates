import { describe, expect, it } from "vitest";
import { phaseFromProjectFileResult, projectFileProgressKey, type ProjectFileProgress } from "../projectFileProgress";

const running: ProjectFileProgress = {
  chatId: "active-chat", operationId: "operation-1", operation: "search",
  searchTarget: "files", phase: "running",
};

describe("Project file progress", () => {
  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required,projects.files.connected-embed-previews
  it("keeps approval and executor waits visible until an explicit terminal result", () => {
    expect(phaseFromProjectFileResult("awaiting_approval")).toBe("awaiting_approval");
    expect(phaseFromProjectFileResult("waiting_for_executor")).toBe("waiting_for_executor");
    expect(projectFileProgressKey({ ...running, phase: "awaiting_approval" })).toBe("approval");
    expect(projectFileProgressKey({ ...running, phase: "waiting_for_executor" })).toBe("waiting_source");
    expect(phaseFromProjectFileResult("completed")).toBe("completed");
    expect(phaseFromProjectFileResult("failed")).toBe("failed");
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it("uses only bounded operation metadata for search and conflict labels", () => {
    expect(projectFileProgressKey(running)).toBe("search_files");
    expect(projectFileProgressKey({ ...running, searchTarget: "content" })).toBe("search_text");
    expect(phaseFromProjectFileResult("conflict")).toBe("conflict");
    expect(projectFileProgressKey({ ...running, phase: "conflict" })).toBe("conflict");
    expect(phaseFromProjectFileResult("private/path.txt")).toBe("failed");
  });
});
