// frontend/packages/ui/src/stores/notFoundPathStore.ts
/**
 * @file notFoundPathStore.ts
 * @description Stores the URL path that triggered a 404 (e.g. "/iphone-review").
 * Set by +page.svelte when it detects the app was loaded for an unknown path.
 * Consumed by ActiveChat.svelte which renders the Not404Screen instead of the
 * normal welcome screen while a path is stored here.
 *
 * Architecture: docs/architecture/404-handling.md (to be written)
 * Flow: unknown path → vercel catch-all → SPA boot → pathname detection →
 *       notFoundPathStore.set(path) → ActiveChat shows Not404Screen →
 *       user action (search or ask AI) → notFoundPathStore.set(null) → normal screen
 */
import { writable } from "svelte/store";

/**
 * The URL path that 404'd (e.g. "/iphone-review"), or null when idle.
 * ActiveChat checks this to decide whether to show the 404 screen.
 */
export const notFoundPathStore = writable<string | null>(null);
