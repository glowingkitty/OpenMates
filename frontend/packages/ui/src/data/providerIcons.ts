// frontend/packages/ui/src/data/providerIcons.ts
//
// Provider icon URL mapping for AI models.
// Uses Vite's import.meta.glob to resolve static asset paths at build time.
// This ensures icons are properly bundled and accessible at runtime.

// Import all provider SVG icons as URLs
// The glob pattern matches the icons used in modelsMetadata
const iconModules = import.meta.glob<string>(
  "@openmates/ui/static/icons/*.svg",
  { eager: true, import: "default", query: "?url" },
);

/**
 * Map of icon path (as stored in modelsMetadata.logo_svg) to resolved URL.
 *
 * Input: "icons/anthropic.svg" (from modelsMetadata)
 * Output: "/assets/anthropic-abc123.svg" (hashed URL for production)
 */
export const providerIconUrls: Record<string, string> = {};

// Build the mapping from relative paths to resolved URLs
for (const [path, url] of Object.entries(iconModules)) {
  // Extract just the "icons/filename.svg" part from the full path
  // Path format: "@openmates/ui/static/icons/anthropic.svg"
  // We want: "icons/anthropic.svg"
  const match = path.match(/\/icons\/([^/]+\.svg)$/);
  if (match) {
    const iconKey = `icons/${match[1]}`;
    providerIconUrls[iconKey] = url;
  }
}

/**
 * Get the resolved URL for a provider icon.
 *
 * @param iconPath - Icon path as stored in modelsMetadata (e.g., "icons/anthropic.svg")
 * @returns Resolved URL for the icon, or the original path as fallback
 */
export function getProviderIconUrl(iconPath: string): string {
  return providerIconUrls[iconPath] || `/${iconPath}`;
}
