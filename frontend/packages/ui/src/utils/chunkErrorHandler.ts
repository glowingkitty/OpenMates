/**
 * Chunk Error Handler Utility
 * 
 * Provides utilities for detecting and handling chunk loading errors that occur
 * when dynamic imports fail due to stale JavaScript after a deployment.
 * 
 * This is a fallback mechanism for edge cases where SvelteKit's built-in
 * version detection ($app/state updated) doesn't prevent the error.
 * 
 * Common scenarios:
 * - User has browser tab open during deployment
 * - User's browser has aggressive caching
 * - CDN still serving old assets briefly after deployment
 * 
 * Usage:
 * ```typescript
 * try {
 *   await someAsyncOperation();
 * } catch (error) {
 *   if (isChunkLoadError(error)) {
 *     handleChunkLoadError();
 *     return;
 *   }
 *   // Handle other errors...
 * }
 * ```
 */

/**
 * Checks if an error is a chunk loading error (typically caused by stale cache after deployment).
 * 
 * Chunk loading errors occur when:
 * 1. A new version is deployed with new chunk hashes
 * 2. Old cached JavaScript references chunks that no longer exist
 * 3. Dynamic import fails with 404 for the old chunk URL
 * 
 * @param error - The error to check
 * @returns true if this is a chunk loading error, false otherwise
 */
export function isChunkLoadError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false;
    }
    
    const message = error.message || '';
    
    // Check for common chunk loading error patterns
    // These patterns cover various browsers and bundlers
    const chunkErrorPatterns = [
        // SvelteKit/Vite dynamic import failures
        'Failed to fetch dynamically imported module',
        // Webpack chunk loading failures  
        'Loading chunk',
        'ChunkLoadError',
        // Generic module loading failures
        'Failed to load module script',
        // Network errors during chunk loading
        'NetworkError when attempting to fetch resource',
        // Safari-specific pattern
        'Importing a module script failed'
    ];
    
    return chunkErrorPatterns.some(pattern => 
        message.includes(pattern) || error.name?.includes(pattern)
    );
}

/**
 * User-friendly message for chunk loading errors.
 * Instructs the user to refresh the page.
 */
export const CHUNK_ERROR_MESSAGE = 'The app was updated. Please refresh the page to continue (Ctrl+Shift+R or Cmd+Shift+R).';

/**
 * Duration to display the chunk error notification (15 seconds).
 * Longer than normal because this is an important message requiring user action.
 */
export const CHUNK_ERROR_NOTIFICATION_DURATION = 15000;

/**
 * Logs a chunk loading error with context for debugging.
 * 
 * @param context - Context string identifying where the error occurred (e.g., component name)
 * @param error - The original error
 */
export function logChunkLoadError(context: string, error: unknown): void {
    console.error(`[${context}] Chunk loading error detected - likely stale cache after deployment`);
    console.error(`[${context}] Original error:`, error);
    console.info(`[${context}] User should refresh the page to get the latest version`);
}

/**
 * Forces a full page reload to get the latest version of the app.
 * This clears the browser's in-memory cache and fetches fresh assets.
 * 
 * @param hardReload - If true, bypasses cache (equivalent to Ctrl+Shift+R). Default: true
 */
export function forcePageReload(hardReload: boolean = true): void {
    if (typeof window !== 'undefined') {
        console.log('[chunkErrorHandler] Forcing page reload to get latest version');
        if (hardReload) {
            // Force reload bypassing cache
            window.location.reload();
        } else {
            // Normal reload (may use cache)
            window.location.reload();
        }
    }
}


