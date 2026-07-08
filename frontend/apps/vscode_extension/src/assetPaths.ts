/*
 * OpenMates VS Code bundled asset path utilities.
 *
 * Purpose: map SvelteKit static bundle paths into VS Code webview resource URIs.
 * Architecture: extension.ts owns VS Code URI conversion; this helper keeps path
 * normalization pure and unit-testable.
 * Security: removes query/hash data and blocks dot-segment traversal.
 */

export function getSafeBundledAssetSegments(assetPath: string): string[] {
  return assetPath
    .replace(/^\/+/, "")
    .split(/[?#]/)[0]
    .split("/")
    .filter((segment) => segment && segment !== ".." && segment !== ".");
}
