/**
 * Offline-aware image loading utility (Svelte action compatible).
 *
 * When images (favicons, thumbnails, preview images) fail to load and the
 * browser is offline, this utility:
 * 1. Shows a CSS-based placeholder (using the image.svg icon via mask-image)
 * 2. Registers the failed image for automatic retry when connectivity returns
 * 3. Cleans up retry listeners when no longer needed
 *
 * IMPORTANT: This is designed to be used as a Svelte action (`use:handleImageError`).
 * It attaches an `error` event listener on mount and cleans up on destroy.
 * It does NOT execute the error logic on mount — only when the image actually fails.
 *
 * Architecture: Uses networkStatusStore for online/offline detection.
 * The retry mechanism subscribes to the store once and retries all pending
 * images when connectivity is restored.
 *
 * Tests: None yet — frontend utility, verified manually.
 */

import { get } from "svelte/store";
import { isOnline } from "../stores/networkStatusStore";

/** Pending image elements waiting for connectivity to retry loading */
const pendingRetries = new Set<HTMLImageElement>();

/** Whether we're already subscribed to the network status store */
let retrySubscriptionActive = false;

/** Unsubscribe function for the network status store subscription */
let unsubscribe: (() => void) | null = null;

/**
 * Placeholder CSS class name applied to images that failed to load offline.
 * The actual styles are defined in theme.css (see C2 implementation).
 */
const PLACEHOLDER_CLASS = "offline-image-placeholder";

/**
 * Svelte action for offline-aware image error handling.
 *
 * Usage: `<img use:handleImageError />`
 *
 * Attaches an `error` event listener on mount. When the image fails to load:
 * - If online: hides the image (server genuinely can't serve it)
 * - If offline: shows a placeholder and registers for retry on reconnect
 *
 * Returns a `destroy` callback that removes the listener and cancels any pending retry.
 *
 * @param img - The HTMLImageElement (provided automatically by Svelte action system)
 * @returns Action lifecycle object with destroy cleanup
 */
export function handleImageError(
  img: HTMLImageElement,
): { destroy: () => void } {
  const onError = () => {
    const online = get(isOnline);
    const src = img.src;

    if (online) {
      // Online but image still failed — genuinely broken, hide it
      img.style.display = "none";
      return;
    }

    // Offline: show placeholder and register for retry
    showPlaceholder(img, src);
    registerForRetry(img);
  };

  img.addEventListener("error", onError);

  return {
    destroy() {
      img.removeEventListener("error", onError);
      cancelImageRetry(img);
    },
  };
}

/**
 * Apply the placeholder visual to a failed image element.
 * Uses CSS class that displays the image.svg icon as a mask.
 */
function showPlaceholder(img: HTMLImageElement, originalSrc: string): void {
  // Store the original src so we can retry later
  img.dataset.offlineOriginalSrc = originalSrc;

  // Hide the broken image icon but keep the element in the layout
  img.style.visibility = "hidden";
  img.style.width = img.style.width || `${img.width || 24}px`;
  img.style.height = img.style.height || `${img.height || 24}px`;

  // Add placeholder class to the parent (so it can show the icon via ::after)
  const parent = img.parentElement;
  if (parent) {
    parent.classList.add(PLACEHOLDER_CLASS);
  }
}

/**
 * Remove the placeholder visual and restore the image.
 */
function removePlaceholder(img: HTMLImageElement): void {
  img.style.visibility = "";
  const parent = img.parentElement;
  if (parent) {
    parent.classList.remove(PLACEHOLDER_CLASS);
  }
  delete img.dataset.offlineOriginalSrc;
}

/**
 * Register an image element for retry when connectivity is restored.
 * Sets up the global subscription if not already active.
 */
function registerForRetry(img: HTMLImageElement): void {
  pendingRetries.add(img);
  ensureRetrySubscription();
}

/**
 * Subscribe to the network status store to retry images when coming back online.
 * Only subscribes once; cleans up when all pending images are handled.
 */
function ensureRetrySubscription(): void {
  if (retrySubscriptionActive) return;
  retrySubscriptionActive = true;

  unsubscribe = isOnline.subscribe((online) => {
    if (online && pendingRetries.size > 0) {
      retryAllPendingImages();
    }
  });
}

/**
 * Retry loading all pending images.
 * Called when the browser reports it's back online.
 */
function retryAllPendingImages(): void {
  const images = Array.from(pendingRetries);
  pendingRetries.clear();

  for (const img of images) {
    // Skip if the element was removed from the DOM
    if (!img.isConnected) continue;

    const originalSrc = img.dataset.offlineOriginalSrc;
    if (!originalSrc) continue;

    // Remove the placeholder
    removePlaceholder(img);

    // Force a reload by resetting the src
    // Adding a cache-buster query param to avoid browser cache of the failed load
    const separator = originalSrc.includes("?") ? "&" : "?";
    img.src = `${originalSrc}${separator}_retry=${Date.now()}`;

    // If this retry also fails (e.g., still offline or server error),
    // the error listener (from the Svelte action) will trigger again
  }

  // If no more pending images, clean up the subscription
  if (pendingRetries.size === 0 && unsubscribe) {
    unsubscribe();
    unsubscribe = null;
    retrySubscriptionActive = false;
  }
}

/**
 * Manually unregister an image from retry (e.g., when the component unmounts).
 * Prevents memory leaks from holding references to detached DOM elements.
 */
export function cancelImageRetry(img: HTMLImageElement): void {
  pendingRetries.delete(img);

  // Clean up subscription if no more pending
  if (pendingRetries.size === 0 && unsubscribe) {
    unsubscribe();
    unsubscribe = null;
    retrySubscriptionActive = false;
  }
}
