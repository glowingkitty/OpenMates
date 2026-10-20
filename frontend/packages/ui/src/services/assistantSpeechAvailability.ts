// Private speech generation follows runtime provider availability. Public audio
// fixtures are playable independently and must not use this generation gate.
import { derived } from "svelte/store";
import { featureAvailabilityStore, userAvailableSkillsStore } from "../stores/appSkillsStore";

export const assistantSpeechGenerationAvailable = derived(
  [userAvailableSkillsStore, featureAvailabilityStore],
  ([skills, features]) => Boolean(
    skills.skillsByApp?.audio?.includes("speak")
    && !features.disabledById?.["app:audio"]
    && !features.disabledById?.["skill:audio:speak"],
  ),
);
