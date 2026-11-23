/**
 * Fictional read-only memory-permission card fixtures.
 * Default shows a measured available-entry count; unknown omits the count;
 * inCall shows the voice-call countdown bar.
 * No account, mailbox, memory mutation or inference is used by these fixtures.
 * Interactive consent recovery is covered by the ChatHistory fixture.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
const category = { key: "openmates-memories", appId: "openmates", displayName: "Memories", entryCount: 1, selected: true };
export default { previewMode: true, previewCategories: [category] };
export const variants = {
  unknown: { previewMode: true, previewCategories: [{ ...category, entryCount: null }] },
  // In a voice call: the countdown bar 40% through its 30 s, then it continues without memories.
  inCall: { previewMode: true, previewCategories: [category], previewCountdownFraction: 0.6 },
};
