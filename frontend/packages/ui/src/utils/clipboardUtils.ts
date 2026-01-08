/**
 * Clipboard Utilities
 * ===================
 * Cross-browser clipboard operations with Safari compatibility.
 * 
 * Safari (especially on iOS and macOS) has strict clipboard API requirements:
 * - Requires HTTPS secure context
 * - Requires user gesture/interaction
 * - Requires document focus
 * - Can fail silently even when the API exists
 * 
 * This module provides a robust copyToClipboard function with:
 * - Modern navigator.clipboard API as primary method
 * - Fallback using document.execCommand('copy') for older browsers
 * - Special handling for iOS Safari
 * - Proper error handling and logging
 */

// ========================================================================
// TYPES
// ========================================================================

/** Result of a clipboard operation */
export interface ClipboardResult {
    success: boolean;
    error?: string;
}

// ========================================================================
// COPY TO CLIPBOARD
// ========================================================================

/**
 * Copy text to clipboard with Safari/iOS fallback support.
 * 
 * Uses navigator.clipboard API first, then falls back to
 * document.execCommand('copy') for browsers where the modern API fails.
 * 
 * @param text - The text to copy to clipboard
 * @returns Promise<ClipboardResult> indicating success or failure
 * 
 * @example
 * const result = await copyToClipboard('Hello World');
 * if (result.success) {
 *     console.log('Copied!');
 * } else {
 *     console.error('Failed:', result.error);
 * }
 */
export async function copyToClipboard(text: string): Promise<ClipboardResult> {
    if (!text) {
        console.error('[clipboardUtils] No text provided to copy');
        return { success: false, error: 'No text provided' };
    }

    let copySuccess = false;

    // Try modern clipboard API first
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            copySuccess = true;
            console.debug('[clipboardUtils] Copied using navigator.clipboard API');
        }
    } catch (err) {
        // Safari and some browsers may reject clipboard access even with user gesture
        console.warn('[clipboardUtils] navigator.clipboard.writeText failed:', err);
    }

    // Fallback for Safari and browsers where clipboard API fails
    if (!copySuccess) {
        try {
            copySuccess = fallbackCopyToClipboard(text);
            if (copySuccess) {
                console.debug('[clipboardUtils] Copied using fallback method');
            }
        } catch (fallbackErr) {
            console.error('[clipboardUtils] Fallback copy error:', fallbackErr);
        }
    }

    if (copySuccess) {
        return { success: true };
    } else {
        return { 
            success: false, 
            error: 'Failed to copy to clipboard. Please copy manually.' 
        };
    }
}

/**
 * Fallback copy method using document.execCommand('copy').
 * Works on older browsers and as a fallback for Safari.
 * 
 * @param text - The text to copy
 * @returns boolean indicating success
 */
function fallbackCopyToClipboard(text: string): boolean {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    
    // Prevent scrolling to bottom on iOS Safari
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '0';
    textArea.style.opacity = '0';
    
    // Prevent keyboard popup on mobile
    textArea.setAttribute('readonly', '');
    
    document.body.appendChild(textArea);

    let success = false;

    try {
        // Handle iOS Safari specifically
        // iOS requires using Range and Selection APIs
        if (isIOS()) {
            const range = document.createRange();
            range.selectNodeContents(textArea);
            const selection = window.getSelection();
            if (selection) {
                selection.removeAllRanges();
                selection.addRange(range);
            }
            textArea.setSelectionRange(0, text.length);
        } else {
            textArea.select();
        }

        success = document.execCommand('copy');
    } catch (err) {
        console.error('[clipboardUtils] execCommand copy failed:', err);
        success = false;
    } finally {
        document.body.removeChild(textArea);
    }

    return success;
}

/**
 * Detect if the current device is running iOS.
 * @returns boolean
 */
function isIOS(): boolean {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) || 
           (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

/**
 * Copy text to clipboard and show alert if all methods fail.
 * This is a convenience function that shows the text to the user
 * for manual copying if clipboard operations fail.
 * 
 * @param text - The text to copy
 * @param alertMessage - Optional custom message for the alert fallback
 * @returns Promise<ClipboardResult>
 */
export async function copyToClipboardWithFallbackAlert(
    text: string, 
    alertMessage?: string
): Promise<ClipboardResult> {
    const result = await copyToClipboard(text);
    
    if (!result.success) {
        // Last resort: show the text in an alert for manual copying
        const message = alertMessage || `Copy this manually:\n\n${text}`;
        alert(message);
        console.warn('[clipboardUtils] Showing alert for manual copy');
    }
    
    return result;
}
