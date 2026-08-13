// frontend/packages/ui/src/config/__tests__/workspaceFeatureGates.test.ts
// Regression coverage for workspace release gates.
// Optional top-level workspaces must follow the current web release list even if
// the backend availability response omits their disabled IDs.

import { describe, expect, it } from "vitest";

import { isWorkspaceFeatureAvailable } from "../workspaceFeatureGates";

describe("isWorkspaceFeatureAvailable", () => {
  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it("keeps chats enabled by default", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", null, true)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it("hides unknown optional workspaces even when backend omits disabled IDs", () => {
    expect(isWorkspaceFeatureAvailable("platform:teams", {})).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it("shows released optional workspaces when backend omits disabled IDs", () => {
    expect(isWorkspaceFeatureAvailable("platform:projects", {})).toBe(true);
    expect(isWorkspaceFeatureAvailable("platform:plans", {})).toBe(true);
    expect(isWorkspaceFeatureAvailable("platform:tasks", {})).toBe(true);
    expect(isWorkspaceFeatureAvailable("platform:workflows", {})).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it("hides every optional header workspace disabled by the release backend", () => {
    const disabled = {
      "platform:projects": true,
      "platform:plans": true,
      "platform:tasks": true,
      "platform:workflows": true,
    } as const;

    expect(isWorkspaceFeatureAvailable("platform:projects", disabled)).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:plans", disabled)).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:tasks", disabled)).toBe(false);
    expect(isWorkspaceFeatureAvailable("platform:workflows", disabled)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
  it("keeps disabled chats hidden if backend explicitly disables them", () => {
    expect(isWorkspaceFeatureAvailable("platform:chats", { "platform:chats": true }, true)).toBe(false);
  });
});
