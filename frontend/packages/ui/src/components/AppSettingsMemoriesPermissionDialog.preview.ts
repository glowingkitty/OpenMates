/**
 * Fictional read-only memory-permission card fixtures.
 * Default shows a measured available-entry count; unknown omits the count.
 * No account, mailbox, memory mutation or inference is used by these fixtures.
 * Interactive consent recovery is covered by the ChatHistory fixture.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
const category = { key: "mail-writing_styles", appId: "mail", displayName: "Writing styles", entryCount: 1, selected: true };
export default { previewMode: true, previewCategories: [category] };
export const variants = {
  unknown: { previewMode: true, previewCategories: [{ ...category, entryCount: null }] },
};
