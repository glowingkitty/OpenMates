/** Deterministic catalogue-growth fixture; no account or backend reads. */
export const layout = 'fill';
export default {};
export const variants = { bookmarks: { bookmarks: true }, bookmarkFailure: { bookmarks: true, failSave: true } };
