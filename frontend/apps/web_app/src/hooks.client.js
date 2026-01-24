// Import from @repo/ui to trigger i18n initialization
// The i18n system (register + init) runs synchronously when setup.ts is imported
// This ensures translations are available when components try to use them
// We import setupI18n but don't call it - just importing it runs the init code
import '@repo/ui';

/**
 * Detects if running on Safari (iOS/iPadOS)
 * Safari has different caching behavior and needs special handling
 */
function isSafari() {
  if (typeof navigator === 'undefined') return false;
  
  // Check for Safari on iOS/iPadOS
  const ua = navigator.userAgent.toLowerCase();
  const isIOS = /iphone|ipad|ipod/.test(ua);
  const isSafariUA = /safari/.test(ua) && !/chrome|crios|fxios/.test(ua);
  
  // Also check for standalone mode (PWA)
  const isStandalone = window.navigator.standalone === true;
  
  return (isIOS && isSafariUA) || isStandalone;
}

/**
 * Forces service worker update on Safari/iOS
 * Safari is notorious for not updating service workers automatically.
 * This function explicitly checks for and installs service worker updates.
 *
 * MODIFIED: Only activate service worker during page load, not during sync completion
 */
async function forceServiceWorkerUpdate() {
  if ('serviceWorker' in navigator) {
    try {
      const registration = await navigator.serviceWorker.getRegistration();

      if (registration) {
        console.log('[hooks.client] Checking for service worker update...');

        // Force update check - Safari often ignores automatic updates
        await registration.update();

        // If a new service worker is waiting, skip waiting
        if (registration.waiting) {
          console.log('[hooks.client] New service worker waiting, will activate on next page load (not immediately during sync)');
          // REMOVED: Immediate activation that causes page reload during sync
          // registration.waiting.postMessage({ type: 'SKIP_WAITING' });
        } else if (registration.installing) {
          console.log('[hooks.client] Service worker is installing, will activate when ready...');
        } else {
          console.log('[hooks.client] Service worker is up to date');
        }
      } else {
        console.log('[hooks.client] No service worker registration found');
      }
    } catch (error) {
      console.error('[hooks.client] Error checking for service worker update:', error);
    }
  } else {
    console.warn('[hooks.client] Service Worker API not available');
  }
}

// Register service worker for PWA functionality
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js')
      .then((registration) => {
        console.debug('Service Worker Registered');
        
        // Safari-specific: Force service worker update check on registration
        // Safari is notorious for not updating service workers automatically
        // This ensures Safari always checks for and installs the latest version
        if (isSafari()) {
          console.debug('[hooks.client] Safari detected - forcing service worker update check');
          // Delay slightly to ensure registration is complete
          setTimeout(() => {
            forceServiceWorkerUpdate().catch(err => {
              console.warn('[hooks.client] Service worker update check failed:', err);
            });
          }, 1000);
        }
        
        // For all browsers: Check for updates periodically (every 5 minutes)
        // MODIFIED: Only check for updates, don't activate immediately to prevent reload during sync
        setInterval(() => {
          registration.update().catch(err => {
            console.debug('[hooks.client] Periodic service worker update check:', err);
          });
        }, 5 * 60 * 1000); // 5 minutes

        // Check for updates on visibility change (when user returns to the app)
        // MODIFIED: Only check for updates, don't activate immediately
        document.addEventListener('visibilitychange', () => {
          if (!document.hidden) {
            console.debug('[hooks.client] App became visible - checking for service worker update');
            registration.update().catch(err => {
              console.debug('[hooks.client] Service worker update check on visibility change:', err);
            });
          }
        });
      })
      .catch(err => console.error('Service Worker registration failed', err));
  }