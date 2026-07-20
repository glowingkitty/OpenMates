// frontend/packages/ui/src/config/__tests__/workspaceFeatureGates.test.ts
// Regression coverage for workspace release gates.
// Optional top-level workspaces must stay hidden until the web build releases
// them, even if an older backend availability response omits their disabled IDs.
// Plans, workflows, and tasks are currently released; projects are not.

import { describe, expect, it } from "vitest";

import { isWorkspaceFeatureAvailable } from "../workspaceFeatureGates";

describe("isWorkspaceFeatureAvailable", () => {
  it("keeps chats enabled by default", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", null, true)).toBe(true);
  });

  it("hides unreleased optional workspaces even when backend omits disabled IDs", () => {
    expect(isWorkspaceFeatureAvailable("platform:projects", {})).toBe(false);
  });

  it("shows released optional workspaces when backend omits disabled IDs", () => {
    expect(isWorkspaceFeatureAvailable("platform:plans", {})).toBe(true);
    expect(isWorkspaceFeatureAvailable("platform:tasks", {})).toBe(true);
    expect(isWorkspaceFeatureAvailable("platform:workflows", {})).toBe(true);
  });

  it("keeps disabled chats hidden if backend explicitly disables them", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", { "platform:chats": true }, true)).toBe(false);
  });
});
