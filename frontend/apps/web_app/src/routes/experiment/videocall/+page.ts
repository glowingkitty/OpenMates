/**
 * Isolated client-rendered route for the video call experiment.
 * Media and auth services require browser APIs unavailable during SSR.
 * The route remains outside the ordinary chat and sidebar shell.
 * Static routing still allows a direct bookmarked URL.
 */
export const ssr = false;
export const csr = true;
export const prerender = true;
