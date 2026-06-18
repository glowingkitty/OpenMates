// frontend/packages/ui/src/stores/__tests__/appSkillsStore.test.ts
//
// Regression coverage for Settings > Apps user-specific skill filtering.
// Apps that have no callable skills can still be legitimate app-store entries
// when they expose direct content embeds, such as Diagrams/Mermaid.

import { afterEach, describe, expect, it } from "vitest";

import {
  appSkillsStore,
  resetUserAvailableSkills,
  userAvailableSkillsStore,
} from "../appSkillsStore";

describe("appSkillsStore", () => {
  afterEach(() => {
    resetUserAvailableSkills();
  });

  it("keeps content-only apps when authenticated skill filtering omits them", () => {
    userAvailableSkillsStore.set({
      initialized: true,
      loading: false,
      skillsByApp: {
        code: ["code"],
      },
    });

    const apps = appSkillsStore.getState().apps;

    expect(apps.diagrams).toMatchObject({
      id: "diagrams",
      skills: [],
      focus_modes: [],
      settings_and_memories: [],
    });
  });
});
