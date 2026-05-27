// Import from @repo/ui to trigger i18n initialization
// The i18n system (register + init) runs synchronously when setup.ts is imported
// This ensures translations are available when components try to use them
// We import setupI18n but don't call it - just importing it runs the init code
import '@repo/ui';

// The Workbox service worker is temporarily retired from app boot.
// Existing registrations are handled by the self-destroying /sw.js build.
