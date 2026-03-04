/**
 * frontend/packages/ui/src/utils/clipboardUtils.ts
 *
 * Unified Clipboard Service — single source of truth for all clipboard operations.
 * Architecture: docs/architecture/embeds.md — "Clipboard Service" section
 *
 * This module provides a tiered write strategy for cross-browser clipboard support:
 *   Tier 1: navigator.clipboard.write() with ClipboardItem (multi-MIME, Chromium/Firefox)
 *   Tier 2: navigator.clipboard.writeText() (plain text only, modern browsers)
 *   Tier 3: document.execCommand('copy') with textarea (legacy + Safari fallback)
 *
 * Safari-specific considerations:
 *   - Clipboard API requires HTTPS + active user gesture (click/keydown)
 *   - The gesture token expires after the first `await` — synchronous invocation is critical
 *   - Safari rejects custom MIME types in ClipboardItem
 *   - iOS Safari requires Range/Selection APIs for textarea copy
 *   - ClipboardItem supports Promises as values, allowing deferred computation
 *
 * All duplicate clipboard implementations across the codebase should import from this
 * module instead of rolling their own fallback chains.
 */

// ── Types ───────────────────────────────────────────────────────────────────

/** Result of a clipboard operation */
export interface ClipboardResult {
  success: boolean;
  method?: "clipboardItem" | "writeText" | "execCommand" | "alert";
  error?: string;
}

/** A single MIME entry for multi-MIME clipboard writes */
export interface ClipboardMimeEntry {
  /** MIME type (e.g., "text/plain", "text/html", "application/x-openmates-embed") */
  mimeType: string;
  /** Content to write — can be a string, Blob, or a Promise resolving to a Blob.
   *  Promises are used for Safari gesture-token safety: the ClipboardItem constructor
   *  accepts Promise<Blob> values, allowing async content generation without breaking
   *  the synchronous invocation requirement. */
  data: string | Blob | Promise<Blob>;
}

// ── Platform Detection ──────────────────────────────────────────────────────

/**
 * Detect if the current device is running iOS.
 * Handles iPad Pro (which reports "MacIntel" as platform).
 */
export function isIOS(): boolean {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/**
 * Detect if the current browser is Safari (including iOS Safari).
 */
function isSafari(): boolean {
  const ua = navigator.userAgent;
  return /^((?!chrome|android).)*safari/i.test(ua);
}

// ── Tier 3: execCommand Fallback ────────────────────────────────────────────

/**
 * Fallback copy method using document.execCommand('copy') with a hidden textarea.
 * Works on legacy browsers and as a fallback for Safari when the Clipboard API fails.
 *
 * Includes iOS-specific handling:
 *   - Range/Selection APIs for iOS Safari
 *   - readonly attribute to prevent keyboard popup
 *   - fontSize: 12pt to prevent iOS zoom-on-focus
 *   - Fixed positioning to prevent scroll jumping
 *
 * @param text - The text to copy
 * @returns boolean indicating success
 */
export function execCommandCopy(text: string): boolean {
  const textArea = document.createElement("textarea");
  textArea.value = text;

  // Prevent scrolling and visibility
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  textArea.style.top = "0";
  textArea.style.opacity = "0";
  textArea.style.fontSize = "12pt"; // Prevents iOS zoom on focus

  // Prevent keyboard popup on mobile
  textArea.setAttribute("readonly", "");

  document.body.appendChild(textArea);

  let success = false;

  try {
    if (isIOS()) {
      // iOS Safari requires Range and Selection APIs
      const range = document.createRange();
      range.selectNodeContents(textArea);
      const selection = window.getSelection();
      if (selection) {
        selection.removeAllRanges();
        selection.addRange(range);
      }
      textArea.setSelectionRange(0, text.length);
    } else {
      textArea.focus();
      textArea.select();
    }

    success = document.execCommand("copy");
  } catch (err) {
    console.error("[ClipboardService] execCommand copy failed:", err);
    success = false;
  } finally {
    document.body.removeChild(textArea);
  }

  return success;
}

// ── Tier 2: writeText ───────────────────────────────────────────────────────

/**
 * Copy plain text to clipboard using the modern Clipboard API with tiered fallbacks.
 *
 * Fallback chain:
 *   1. navigator.clipboard.writeText() — modern browsers
 *   2. document.execCommand('copy') — legacy + Safari fallback
 *
 * @param text - The text to copy to clipboard
 * @returns Promise<ClipboardResult> indicating success or failure
 */
export async function copyToClipboard(text: string): Promise<ClipboardResult> {
  if (!text) {
    console.error("[ClipboardService] No text provided to copy");
    return { success: false, error: "No text provided" };
  }

  // Tier 2: Modern Clipboard API
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      console.debug(
        "[ClipboardService] Copied using navigator.clipboard.writeText",
      );
      return { success: true, method: "writeText" };
    }
  } catch (err) {
    console.warn(
      "[ClipboardService] navigator.clipboard.writeText failed:",
      err,
    );
  }

  // Tier 3: execCommand fallback
  try {
    if (execCommandCopy(text)) {
      console.debug("[ClipboardService] Copied using execCommand fallback");
      return { success: true, method: "execCommand" };
    }
  } catch (err) {
    console.error("[ClipboardService] execCommand fallback failed:", err);
  }

  return {
    success: false,
    error: "Failed to copy to clipboard. Please copy manually.",
  };
}

// ── Tier 1: Multi-MIME ClipboardItem Write ──────────────────────────────────

/**
 * Write multiple MIME types to the clipboard using ClipboardItem.
 * This is the most capable tier — supports text/plain + text/html + custom MIME types.
 *
 * CRITICAL: This function must be called synchronously from a user gesture handler.
 * Do NOT `await` anything before calling this function — Safari's gesture token expires
 * after the first microtask boundary (await). The ClipboardItem constructor accepts
 * Promise<Blob> values, which allows deferring content generation while keeping the
 * clipboard.write() call in the synchronous gesture context.
 *
 * Fallback chain:
 *   1. ClipboardItem with all MIME types (Chromium/Firefox)
 *   2. ClipboardItem with text/ MIME types only (Safari rejects custom MIME types)
 *   3. navigator.clipboard.writeText (plain text only)
 *   4. document.execCommand('copy') (legacy textarea)
 *
 * @param entries - Array of MIME entries to write
 * @param plainTextFallback - Plain text to use for Tier 2/3 fallbacks
 * @returns Promise<ClipboardResult>
 *
 * @example
 * // Call synchronously from click handler (no await before this call)
 * writeMultiMime([
 *   { mimeType: 'text/plain', data: 'Hello' },
 *   { mimeType: 'text/html', data: '<b>Hello</b>' },
 *   { mimeType: 'application/x-myapp-data', data: JSON.stringify({ id: '123' }) },
 * ], 'Hello');
 */
export async function writeMultiMime(
  entries: ClipboardMimeEntry[],
  plainTextFallback: string,
): Promise<ClipboardResult> {
  // Tier 1: ClipboardItem with all MIME types
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    try {
      const blobMap: Record<string, Blob | Promise<Blob>> = {};
      for (const entry of entries) {
        if (entry.data instanceof Blob) {
          blobMap[entry.mimeType] = entry.data;
        } else if (entry.data instanceof Promise) {
          blobMap[entry.mimeType] = entry.data;
        } else {
          blobMap[entry.mimeType] = new Blob([entry.data], {
            type: entry.mimeType,
          });
        }
      }

      const item = new ClipboardItem(blobMap);
      await navigator.clipboard.write([item]);
      console.debug(
        `[ClipboardService] Wrote ${entries.length} MIME type(s) via ClipboardItem`,
      );
      return { success: true, method: "clipboardItem" };
    } catch (err) {
      console.warn(
        "[ClipboardService] ClipboardItem with all MIME types failed:",
        err,
      );

      // Tier 1b: Safari fallback — retry with only text/* MIME types
      // Safari rejects custom MIME types (application/x-*)
      if (isSafari()) {
        try {
          const textEntries = entries.filter((e) =>
            e.mimeType.startsWith("text/"),
          );
          if (textEntries.length > 0) {
            const blobMap: Record<string, Blob | Promise<Blob>> = {};
            for (const entry of textEntries) {
              if (entry.data instanceof Blob) {
                blobMap[entry.mimeType] = entry.data;
              } else if (entry.data instanceof Promise) {
                blobMap[entry.mimeType] = entry.data;
              } else {
                blobMap[entry.mimeType] = new Blob([entry.data], {
                  type: entry.mimeType,
                });
              }
            }

            const item = new ClipboardItem(blobMap);
            await navigator.clipboard.write([item]);
            console.debug(
              `[ClipboardService] Safari: wrote ${textEntries.length} text/* MIME type(s) via ClipboardItem`,
            );
            return { success: true, method: "clipboardItem" };
          }
        } catch (safariErr) {
          console.warn(
            "[ClipboardService] Safari ClipboardItem fallback failed:",
            safariErr,
          );
        }
      }
    }
  }

  // Tier 2/3: plain text fallbacks
  return copyToClipboard(plainTextFallback);
}

// ── Convenience Functions ───────────────────────────────────────────────────

/**
 * Copy text to clipboard and show an alert if all methods fail.
 * Convenience wrapper for UI code that wants a last-resort manual copy.
 *
 * @param text - The text to copy
 * @param alertMessage - Optional custom message for the alert fallback
 * @returns Promise<ClipboardResult>
 */
export async function copyToClipboardWithFallbackAlert(
  text: string,
  alertMessage?: string,
): Promise<ClipboardResult> {
  const result = await copyToClipboard(text);

  if (!result.success) {
    const message = alertMessage || `Copy this manually:\n\n${text}`;
    alert(message);
    console.warn("[ClipboardService] Showing alert for manual copy");
    return { success: false, method: "alert", error: result.error };
  }

  return result;
}
