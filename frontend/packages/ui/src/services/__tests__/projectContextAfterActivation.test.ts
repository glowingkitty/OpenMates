import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  focusDocuments: vi.fn(),
  referenceDocuments: vi.fn(),
}));

vi.mock("../agenticProjectContextService", () => ({
  collectProjectFocusCatalog: mocks.catalog,
  collectPrivateFocusForRequest: mocks.focusDocuments,
  collectProjectReferenceDocuments: mocks.referenceDocuments,
}));

import { addProjectFocusContextAfterActivation } from "../projectContextAfterActivation";

describe("Project context after an @Project mention activates the Project", () => {
  beforeEach(() => {
    mocks.catalog.mockReset();
    mocks.focusDocuments.mockReset();
    mocks.referenceDocuments.mockReset();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-layering
  it("adds the stored Focus catalog and its selected body to the first turn", async () => {
    const entry = { kind: "focus", id: "focus-item", title: "Add a new provider", revision: "r1" };
    const body = { item_id: "focus-item", revision: "r1", document: "---\nname: Add a new provider\n---\nSteps" };
    mocks.catalog.mockResolvedValue([entry]);
    mocks.focusDocuments.mockResolvedValue([body]);
    mocks.referenceDocuments.mockResolvedValue([]);
    const payload: Record<string, unknown> = {};

    await addProjectFocusContextAfterActivation("chat-1", "Please add a weather data provider.", payload);

    expect(mocks.catalog).toHaveBeenCalledWith({ chatId: "chat-1" });
    expect(mocks.focusDocuments).toHaveBeenCalledWith({ chatId: "chat-1", text: "Please add a weather data provider." });
    expect(payload.project_focus_catalog).toEqual([entry]);
    expect(payload.project_focus_documents).toEqual([body]);
    expect(payload).not.toHaveProperty("project_context_documents");
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-layering
  it("leaves a failed read out without blocking the other fields", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    mocks.catalog.mockResolvedValue([{ kind: "focus", id: "focus-item", revision: "r1" }]);
    mocks.focusDocuments.mockRejectedValue(new Error("focus_selection_limit"));
    mocks.referenceDocuments.mockResolvedValue([{ item_id: "spec", kind: "spec", document: "x", revision: "r2" }]);
    const payload: Record<string, unknown> = {};

    await addProjectFocusContextAfterActivation("chat-1", "text", payload);

    expect(payload.project_focus_catalog).toHaveLength(1);
    expect(payload).not.toHaveProperty("project_focus_documents");
    expect(payload.project_context_documents).toHaveLength(1);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
