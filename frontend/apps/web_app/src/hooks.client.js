// Import from @repo/ui to trigger i18n initialization
// The i18n system (register + init) runs synchronously when setup.ts is imported
// This ensures translations are available when components try to use them
// We import setupI18n but don't call it - just importing it runs the init code
import '@repo/ui';

// Register service worker for PWA functionality
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js')
      .then(() => console.debug('Service Worker Registered'))
      .catch(err => console.error('Service Worker registration failed', err));
  }