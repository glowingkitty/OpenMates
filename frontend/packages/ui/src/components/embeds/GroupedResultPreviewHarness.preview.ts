export default { app: 'home' };
export const variants = {
  events: { app: 'events' },
  shortCode: { app: 'code' },
  skillCallsProcessing: { skillCalls: true, skillStatus: 'processing' },
  mixedSkillCalls: { skillCalls: true, mixedSkills: true },
  narrowCopy: { narrowCopy: true },
  skillCallsFinished: { skillCalls: true, skillStatus: 'finished' },
};
