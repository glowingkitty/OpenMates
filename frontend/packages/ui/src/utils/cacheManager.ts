/**
 * Cache Manager Utility
 * 
 * Provides utilities to manage browser cache storage and handle quota exceeded errors.
 * This helps prevent QuotaExceededError from accumulating in service worker caches.
 */

/**
 * Clears all service worker caches
 * Use this if you're experiencing QuotaExceededError issues
 */
export async function clearAllServiceWorkerCaches(): Promise<void> {
    try {
        if ('caches' in self) {
            const cacheNames = await caches.keys();
            console.log(`[CacheManager] Found ${cacheNames.length} caches to clear:`, cacheNames);
            
            await Promise.all(
                cacheNames.map(cacheName => {
                    console.log(`[CacheManager] Deleting cache: ${cacheName}`);
                    return caches.delete(cacheName);
                })
            );
            
            console.log('[CacheManager] ✅ All service worker caches cleared');
        } else {
            console.warn('[CacheManager] CacheStorage API not available');
        }
    } catch (error) {
        console.error('[CacheManager] Error clearing caches:', error);
        throw error;
    }
}

/**
 * Gets the total size of all caches (approximate)
 * Note: This is an approximation as browsers don't provide exact cache sizes
 */
export async function getCacheStorageInfo(): Promise<{
    cacheCount: number;
    cacheNames: string[];
}> {
    try {
        if ('caches' in self) {
            const cacheNames = await caches.keys();
            return {
                cacheCount: cacheNames.length,
                cacheNames
            };
        }
        return {
            cacheCount: 0,
            cacheNames: []
        };
    } catch (error) {
        console.error('[CacheManager] Error getting cache info:', error);
        return {
            cacheCount: 0,
            cacheNames: []
        };
    }
}

/**
 * Clears a specific cache by name
 * @param cacheName - Name of the cache to clear
 */
export async function clearCache(cacheName: string): Promise<boolean> {
    try {
        if ('caches' in self) {
            const deleted = await caches.delete(cacheName);
            if (deleted) {
                console.log(`[CacheManager] ✅ Cleared cache: ${cacheName}`);
            } else {
                console.warn(`[CacheManager] Cache not found: ${cacheName}`);
            }
            return deleted;
        }
        return false;
    } catch (error) {
        console.error(`[CacheManager] Error clearing cache ${cacheName}:`, error);
        return false;
    }
}

/**
 * Wraps a cache operation with quota error handling
 * If a QuotaExceededError occurs, it will attempt to clear old caches and retry
 * 
 * @param operation - The cache operation to perform
 * @param retryCount - Maximum number of retries (default: 1)
 */
export async function withQuotaErrorHandling<T>(
    operation: () => Promise<T>,
    retryCount: number = 1
): Promise<T> {
    try {
        return await operation();
    } catch (error) {
        if (error instanceof DOMException && error.name === 'QuotaExceededError') {
            console.warn('[CacheManager] QuotaExceededError detected, attempting to clear old caches...');
            
            if (retryCount > 0) {
                // Clear old caches and retry
                await clearAllServiceWorkerCaches();
                
                // Retry the operation
                return await withQuotaErrorHandling(operation, retryCount - 1);
            } else {
                console.error('[CacheManager] QuotaExceededError persists after cache cleanup');
                throw error;
            }
        }
        // Re-throw non-quota errors
        throw error;
    }
}

/**
 * Forces service worker update on Safari/iOS
 * Safari is notorious for not updating service workers automatically.
 * This function explicitly checks for and installs service worker updates.
 * 
 * Call this on app initialization or when user navigates to ensure latest version.
 */
export async function forceServiceWorkerUpdate(): Promise<void> {
    if ('serviceWorker' in navigator) {
        try {
            const registration = await navigator.serviceWorker.getRegistration();
            
            if (registration) {
                console.log('[CacheManager] Checking for service worker update...');
                
                // Force update check - Safari often ignores automatic updates
                await registration.update();
                
                // If a new service worker is waiting, skip waiting and reload
                if (registration.waiting) {
                    console.log('[CacheManager] New service worker waiting, activating...');
                    
                    // Send skip waiting message to activate immediately
                    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                    
                    // Wait a moment for the service worker to activate
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    
                    // Reload the page to use the new service worker (optional, can be disabled)
                    // Uncomment the line below if you want automatic reload on update
                    // window.location.reload();
                } else if (registration.installing) {
                    console.log('[CacheManager] Service worker is installing, will activate when ready...');
                } else {
                    console.log('[CacheManager] Service worker is up to date');
                }
            } else {
                console.log('[CacheManager] No service worker registration found');
            }
        } catch (error) {
            console.error('[CacheManager] Error checking for service worker update:', error);
        }
    } else {
        console.warn('[CacheManager] Service Worker API not available');
    }
}

/**
 * Detects if running on Safari (iOS/iPadOS)
 * Safari has different caching behavior and needs special handling
 */
export function isSafari(): boolean {
    if (typeof navigator === 'undefined') return false;
    
    // Check for Safari on iOS/iPadOS
    const ua = navigator.userAgent.toLowerCase();
    const isIOS = /iphone|ipad|ipod/.test(ua);
    const isSafariUA = /safari/.test(ua) && !/chrome|crios|fxios/.test(ua);
    
    // Also check for standalone mode (PWA)
    const isStandalone = (window.navigator as any).standalone === true;
    
    return (isIOS && isSafariUA) || isStandalone;
}

