/**
 * Synthetic memory entries exercise production saved-preview controls.
 * Cards read the actual memory store, and forget uses its real deletion path.
 * Only outbound synchronization and the explicit failure variant are isolated.
 * The unrelated entry proves that lookup and removal use exact embed identity.
 * Access: /dev/preview/embeds/SavedResultPreviewFixture?chrome=0
 */
export default {};
export const variants = { unsaved: { saved: false }, failure: { failDelete: true }, grid: { mode: 'grid' } };
