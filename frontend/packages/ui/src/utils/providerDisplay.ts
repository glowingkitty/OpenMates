// frontend/packages/ui/src/utils/providerDisplay.ts
//
// Helpers for rendering provider display names in the UI.
// Model metadata (auto-generated from backend YAML) uses server names like
// "Anthropic API" or "OpenAI API". For the settings UI we strip the trailing
// " API" suffix so users see cleaner names (e.g. "Anthropic", "OpenAI").

/**
 * Simplify a provider/server display name for UI rendering.
 * Removes a trailing " API" suffix if present; otherwise returns the name as-is.
 */
export function simplifyProviderName(name: string | undefined | null): string {
    if (!name) return '';
    return name.replace(/\s+API$/i, '').trim();
}
