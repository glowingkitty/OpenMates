// frontend/packages/ui/src/data/providerIcons.ts
//
// Provider icon URL mapping for AI models.
// Uses Vite's import.meta.glob to resolve static asset paths at build time.
// This ensures icons are properly bundled and accessible at runtime.

// Import all provider icons as URLs
// The glob pattern matches the icons used in modelsMetadata
const iconModules = import.meta.glob<string>(
  "@openmates/ui/static/icons/*.{svg,png,jpg,jpeg}",
  { eager: true, import: "default", query: "?url" },
);

/**
 * Map of icon path (as stored in modelsMetadata.logo_svg) to resolved URL.
 *
 * Input: "icons/anthropic.svg" (from modelsMetadata)
 * Output: "/assets/anthropic-abc123.svg" (hashed URL for production)
 */
export const providerIconUrls: Record<string, string> = {};

// Build the mapping from relative paths to resolved URLs.
// Skip server.svg — it is handled as a self-contained data-URL fallback
// to avoid Vite asset resolution failures in deployed builds.
for (const [path, url] of Object.entries(iconModules)) {
  if (path.endsWith("/icons/server.svg")) continue;
  // Extract just the "icons/filename.ext" part from the full path
  // Path format: "@openmates/ui/static/icons/anthropic.svg"
  // We want: "icons/anthropic.svg"
  const match = path.match(/\/icons\/([^/]+\.(?:svg|png|jpg|jpeg))$/);
  if (match) {
    const iconKey = `icons/${match[1]}`;
    providerIconUrls[iconKey] = url;
  }
}

// Inline fallback server icon as a base64 data URL. Unlike Vite-resolved
// asset URLs (which can 404 in production builds when the asset is not
// bundled for a given chunk), this always loads because it is self-contained.
// Also unlike URL-encoded `data:image/svg+xml,` which Chromium versions
// occasionally report as naturalWidth=0, the base64 format is universally
// supported in modern browsers with no known rendering issues.
// The SVG matches frontend/packages/ui/static/icons/server.svg.
const FALLBACK_SERVER_SVG =
  "data:image/svg+xml;base64," +
  btoa(
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">' +
      '<path d="M6.222 0h35.556c.59 0 1.154.23 1.571.639.417.41.651.964.651 1.543v8.727c0 .579-.234 1.134-.65 1.543-.418.409-.983.639-1.572.639H6.222c-.59 0-1.154-.23-1.571-.64A2.162 2.162 0 014 10.91V2.182c0-.579.234-1.134.65-1.543C5.069.229 5.634 0 6.223 0zm0 17.454h35.556c.59 0 1.154.23 1.571.64.417.409.651.964.651 1.542v8.728c0 .578-.234 1.133-.65 1.542-.418.41-.983.64-1.572.64H6.222c-.59 0-1.154-.23-1.571-.64A2.162 2.162 0 014 28.364v-8.728c0-.578.234-1.133.65-1.542.418-.41.983-.64 1.572-.64zm0 17.455h35.556c.59 0 1.154.23 1.571.64.417.408.651.963.651 1.542v8.727c0 .579-.234 1.134-.65 1.543-.418.41-.983.639-1.572.639H6.222c-.59 0-1.154-.23-1.571-.639A2.162 2.162 0 014 45.818v-8.727c0-.579.234-1.134.65-1.543.418-.409.983-.639 1.572-.639zM17.333 8.727h2.223V4.364h-2.223v4.363zm0 17.455h2.223v-4.364h-2.223v4.364zm0 17.454h2.223v-4.363h-2.223v4.363zM8.444 4.364v4.363h4.445V4.364H8.444zm0 17.454v4.364h4.445v-4.364H8.444zm0 17.455v4.363h4.445v-4.363H8.444z" fill="#000"/></svg>',
  );

/**
 * Get the resolved URL for a provider icon.
 *
 * @param iconPath - Icon path as stored in modelsMetadata (e.g., "icons/anthropic.svg")
 * @returns Resolved URL for the icon, or a self-contained base64 data-URL fallback
 *   of the server icon for unknown/unconfigured providers
 */
export function getProviderIconUrl(iconPath: string): string {
  return providerIconUrls[iconPath] || FALLBACK_SERVER_SVG;
}
