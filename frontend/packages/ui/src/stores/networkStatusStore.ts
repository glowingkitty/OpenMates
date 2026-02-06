// frontend/packages/ui/src/stores/networkStatusStore.ts
/**
 * @file networkStatusStore.ts
 * @description Reactive store tracking browser online/offline status.
 *
 * Uses the browser's `navigator.onLine` property and listens for
 * `online` / `offline` events on `window` to keep the store in sync.
 *
 * Other parts of the app (e.g. OfflineBanner, WebSocket reconnection)
 * can subscribe to this store instead of managing their own listeners.
 *
 * The store is initialised lazily on first subscription (SSR-safe).
 */
import { readable } from "svelte/store";

/**
 * `true` when the browser reports it has network connectivity,
 * `false` when it does not. Defaults to `true` during SSR.
 */
export const isOnline = readable<boolean>(true, (set) => {
  // SSR guard – window/navigator are not available on the server
  if (typeof window === "undefined") return;

  // Seed with the current status
  set(navigator.onLine);

  const handleOnline = () => {
    console.info("[networkStatusStore] Browser reports: online");
    set(true);
  };

  const handleOffline = () => {
    console.info("[networkStatusStore] Browser reports: offline");
    set(false);
  };

  window.addEventListener("online", handleOnline);
  window.addEventListener("offline", handleOffline);

  // Cleanup listeners when all subscribers unsubscribe
  return () => {
    window.removeEventListener("online", handleOnline);
    window.removeEventListener("offline", handleOffline);
  };
});
