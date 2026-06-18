// frontend/packages/ui/src/stores/__tests__/appSkillsStore.test.ts
//
// Regression coverage for Settings > Apps user-specific skill filtering.
// Deactivated apps must stay out of the app skills store even when dormant
// implementation files remain in the repository for future refinement.

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

  it("omits deactivated Diagrams app metadata", () => {
    userAvailableSkillsStore.set({
      initialized: true,
      loading: false,
      skillsByApp: {
        code: ["code"],
      },
    });

    const apps = appSkillsStore.getState().apps;

    expect(apps.diagrams).toBeUndefined();
  });
});
