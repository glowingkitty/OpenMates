import { expect, it, vi } from "vitest";
import { get } from "svelte/store";

vi.mock("../../stores/appSkillsStore", async () => {
  const { writable } = await import("svelte/store");
  return {
    userAvailableSkillsStore: writable({ skillsByApp: null, assistantSpeechAvailable: false }),
    featureAvailabilityStore: writable({ disabledById: {} }),
  };
});

import { featureAvailabilityStore, userAvailableSkillsStore } from "../../stores/appSkillsStore";
import { assistantSpeechGenerationAvailable } from "../assistantSpeechAvailability";

// contract-test: supporting surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable
it("requires confirmed runtime speech availability and follows feature changes", () => {
  const unsubscribe = assistantSpeechGenerationAvailable.subscribe(() => {});
  expect(get(assistantSpeechGenerationAvailable)).toBe(false);
  userAvailableSkillsStore.update(state => ({ ...state, skillsByApp: { audio: ["generate"] } }));
  expect(get(assistantSpeechGenerationAvailable)).toBe(false);
  userAvailableSkillsStore.update(state => ({ ...state, skillsByApp: { audio: [] }, assistantSpeechAvailable: true }));
  expect(get(assistantSpeechGenerationAvailable)).toBe(true);
  for (const featureId of ["app:audio", "skill:audio:speak"]) {
    featureAvailabilityStore.update(state => ({ ...state, disabledById: { [featureId]: true } }));
    expect(get(assistantSpeechGenerationAvailable)).toBe(false);
    featureAvailabilityStore.update(state => ({ ...state, disabledById: {} }));
    expect(get(assistantSpeechGenerationAvailable)).toBe(true);
  }
  userAvailableSkillsStore.update(state => ({ ...state, skillsByApp: null, assistantSpeechAvailable: false }));
  expect(get(assistantSpeechGenerationAvailable)).toBe(false);
  unsubscribe();
});
