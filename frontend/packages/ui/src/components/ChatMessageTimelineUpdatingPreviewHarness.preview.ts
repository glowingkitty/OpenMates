/** Deterministic catalogue-growth fixture; no account or backend reads. */
export const layout = 'fill';
export default {};
export const variants = { followUp: { followUp: true }, bookmarks: { bookmarks: true }, bookmarkFailure: { bookmarks: true, failSave: true } };
