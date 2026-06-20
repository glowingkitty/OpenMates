// frontend/packages/ui/src/stores/__tests__/appSkillsStore.test.ts
//
// Regression coverage for Settings > Apps user-specific skill filtering.
// Deactivated apps must stay out of the app skills store even when dormant
// implementation files remain in the repository for future refinement.

import { afterEach, describe, expect, it } from "vitest";

import {
  appSkillsStore,
  featureAvailabilityStore,
  resetFeatureAvailability,
  resetUserAvailableSkills,
  userAvailableSkillsStore,
} from "../appSkillsStore";

describe("appSkillsStore", () => {
  afterEach(() => {
    resetFeatureAvailability();
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

  it("omits apps disabled by effective feature availability", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "app:videos": true },
    });

    const apps = appSkillsStore.getState().apps;

    expect(apps.videos).toBeUndefined();
  });

  it("filters disabled skills and recomputes providers", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "skill:web:search": true },
    });

    const web = appSkillsStore.getState().apps.web;

    expect(web.skills.some((skill) => skill.id === "search")).toBe(false);
    expect(web.providers ?? []).not.toContain("Brave");
  });

  it("filters disabled settings and memory fields", () => {
    featureAvailabilityStore.set({
      initialized: true,
      loading: false,
      disabledById: { "memory:ai:communication_style": true },
    });

    const ai = appSkillsStore.getState().apps.ai;

    expect(ai.settings_and_memories.some((memory) => memory.id === "communication_style")).toBe(false);
  });
});
