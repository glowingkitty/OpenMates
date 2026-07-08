// frontend/packages/ui/src/config/__tests__/workspaceFeatureGates.test.ts
// Regression coverage for workspace release gates.
// Optional top-level workspaces must stay hidden until the web build releases
// them, even if an older backend availability response omits their disabled IDs.
// Chats remain the only default visible workspace in the current production UI.

import { describe, expect, it } from "vitest";

import { isWorkspaceFeatureAvailable } from "../workspaceFeatureGates";

describe("isWorkspaceFeatureAvailable", () => {
  it("keeps chats enabled by default", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", null, true)).toBe(true);
  });

  it("hides unreleased optional workspaces even when backend omits disabled IDs", () => {
    expect(isWorkspaceFeatureAvailable("platform:plans", {})).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:projects", {})).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:tasks", {})).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:workflows", {})).toBe(false);
  });

  it("keeps disabled chats hidden if backend explicitly disables them", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", { "platform:chats": true }, true)).toBe(false);
  });
});
