/**
 * Pure client-side SPA configuration
 * Pre-renders for SEO, then hydrates client-side for offline-first PWA
 */
export const prerender = true; // Pre-render for SEO
export const ssr = false; // Disable runtime SSR
export const csr = true; // Enable client-side routing

