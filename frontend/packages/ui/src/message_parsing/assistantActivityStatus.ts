// frontend/packages/ui/src/message_parsing/assistantActivityStatus.ts
// Classify a live app-skill run from protocol skill IDs, never query text.
// Read/search/list/info calls show Researching; mutations show Working.
// Unknown IDs stay Researching until metadata gives a stronger signal.
// A mixed parallel run is Working if any call performs an action.

export type AssistantSkillPhase = 'researching' | 'working';

const ACTION_SKILL_ID = /^(?:add|cancel|clean|create|delete|edit|generate|keep-temporary|modify|remove|run|schedule|send|set|share|speak|transcribe|translate|update|vectorize|write)(?:$|[-_])/;

export function classifyAssistantSkillPhase(skillIds: readonly string[]): AssistantSkillPhase {
  return skillIds.some((id) => ACTION_SKILL_ID.test(id.toLowerCase()))
    ? 'working' : 'researching';
}
